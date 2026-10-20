import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.agents.contract import ReplayMismatch, RunRecord, replay
from src.agents.project_manager import (
    BUILD_BOARD,
    SPEC,
    PriorityAgent,
    PriorityAgentError,
    build_board,
)

ROOT = Path(__file__).resolve().parents[2]
BOT = "github-actions[bot]"
MARKER = "<!-- TIM_PRIORITY_BOARD_V1 -->"
CLOCK = "2026-09-29T20:00:00+00:00"


def issue(number, title, *, state="open", labels=(), body="", author="someone"):
    return {"number": number, "title": title, "state": state, "body": body,
            "labels": [{"name": label} for label in labels],
            "updated_at": "2026-09-27T10:00:00Z", "user": {"login": author}}


class FakeGitHub:
    def __init__(self, issues, comments=None, pull_requests=None):
        self.issues = issues
        self.comments = comments or {}
        self.pull_requests = pull_requests or []
        self.created, self.updated = [], []

    def list_issues(self, state="open"):
        return self.issues

    def list_comments(self, number):
        return self.comments.get(number, [])

    def list_open_pull_requests(self):
        return self.pull_requests

    def create_issue(self, title, body):
        self.created.append((title, body))
        return {"number": 999}

    def update_issue(self, number, body):
        self.updated.append((number, body))
        return {"number": number}


def agent(client):
    return PriorityAgent(client, "TIM Priority Board", "TIM_PRIORITY_BOARD_V1", "Europe/Berlin", 5,
                         repository="owner/repo", clock=lambda: CLOCK)


def work():
    return [issue(12, "Task Engine", labels=("status:active",)),
            issue(13, "Incident Foundation", body="Blocked by: #12"),
            issue(22, "Old", labels=("archive",))]


def test_spec_is_least_privilege_and_keeps_common_forbidden_actions():
    assert set(SPEC.allowed_actions) == {"read_github_snapshot", "build_priority_board",
                                         "create_priority_board_issue", "update_priority_board_issue"}
    assert "order_creation" in SPEC.forbidden_actions
    assert "git_merge_or_push_without_authorization" in SPEC.forbidden_actions


def test_board_is_deterministic_for_the_same_snapshot():
    first, second = agent(FakeGitHub(work())), agent(FakeGitHub(list(reversed(work()))))
    _, board_a = first.run(dry_run=True)
    _, board_b = second.run(dry_run=True)
    assert board_a == board_b
    assert first.last_record == second.last_record
    assert f"Aktualisiert: `{CLOCK}`" in board_a


def test_run_record_replays_and_detects_tampering():
    pm = agent(FakeGitHub(work()))
    pm.run(dry_run=True)
    restored = RunRecord.from_dict(json.loads(json.dumps(pm.last_record.to_dict())))
    assert restored.action == BUILD_BOARD
    assert replay(SPEC, build_board, restored) == pm.last_record
    with pytest.raises(ReplayMismatch):
        replay(SPEC, lambda snapshot: {**build_board(snapshot), "board": "changed"}, restored)


def test_dry_run_never_writes():
    client = FakeGitHub([*work(), issue(500, "TIM Priority Board", body=MARKER, author=BOT)])
    number, board = agent(client).run(dry_run=True)
    assert number == 500 and "#12 — Task Engine" in board
    assert client.created == [] and client.updated == []


def test_foreign_issue_quoting_the_marker_is_not_hijacked():
    quoting = issue(40, "Discuss the board", body=f"Example: {MARKER}", author="someone")
    wrong_title = issue(41, "Something else", body=MARKER, author=BOT)
    client = FakeGitHub([*work(), quoting, wrong_title])
    number, board = agent(client).run()
    assert number == 999 and len(client.created) == 1
    assert client.updated == []
    assert "#40 — Discuss the board" in board


def test_foreign_marker_issues_cannot_block_the_agent():
    fakes = [issue(n, "TIM Priority Board", body=MARKER, author="someone") for n in (40, 41)]
    client = FakeGitHub([*work(), *fakes, issue(500, "TIM Priority Board", body=MARKER, author=BOT)])
    number, _ = agent(client).run()
    assert number == 500 and client.updated[0][0] == 500


def test_two_genuine_boards_fail_closed_without_write():
    boards = [issue(n, "TIM Priority Board", body=MARKER, author=BOT) for n in (500, 501)]
    client = FakeGitHub([*work(), *boards])
    with pytest.raises(PriorityAgentError, match="Mehrdeutige"):
        agent(client).run()
    assert client.created == [] and client.updated == []


def test_board_comments_are_not_read_and_pull_requests_are_minimised():
    client = FakeGitHub(
        [*work(), issue(500, "TIM Priority Board", body=MARKER, author=BOT)],
        comments={500: [{"body": "STATUS: BLOCKED"}]},
        pull_requests=[{"number": 80, "title": "PR", "mergeable_state": "dirty", "head": {"sha": "x"},
                        "statusCheckRollup": [{"name": "ci", "conclusion": "failure", "output": "log"}]}])
    snapshot = agent(client).collect_snapshot()
    assert "500" not in snapshot["comments"]
    assert snapshot["pull_requests"] == [{"number": 80, "title": "PR", "mergeable_state": "dirty",
                                          "statusCheckRollup": [{"name": "ci", "conclusion": "failure"}]}]


def test_closed_issues_are_never_ranked_but_still_resolve_dependencies():
    client = FakeGitHub([issue(12, "Open task", body="Depends on: #7"),
                         issue(7, "Long closed", state="closed"),
                         issue(300, "TIM Priority Board", state="closed", body=MARKER, author=BOT)])
    number, board = agent(client).run()
    assert "#7 — Long closed" not in board
    assert "(`READY`)" in board and "WAITING" not in board.split("## Warteschlange")[0]
    assert number == 999 and client.updated == []


def test_unknown_snapshot_schema_is_rejected():
    with pytest.raises(PriorityAgentError):
        build_board({"schema": "other"})


def test_cli_replays_a_recorded_run(tmp_path):
    pm = agent(FakeGitHub(work()))
    pm.run(dry_run=True)
    path = tmp_path / "record.json"
    path.write_text(json.dumps(pm.last_record.to_dict()))
    ok = subprocess.run([sys.executable, "scripts/tim_priority_agent.py", "--replay", str(path)],
                        cwd=ROOT, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert "Replay OK" in ok.stdout
    data = json.loads(path.read_text())
    data["output"]["board"] += "tampered"
    path.write_text(json.dumps(data))
    bad = subprocess.run([sys.executable, "scripts/tim_priority_agent.py", "--replay", str(path)],
                         cwd=ROOT, capture_output=True, text=True)
    assert bad.returncode == 1 and "Replay failed" in bad.stderr


def test_workflow_enforces_timeout_concurrency_and_pipefail():
    workflow = (ROOT / ".github/workflows/tim-priority-board.yml").read_text()
    assert "timeout-minutes: 10" in workflow
    assert "concurrency:" in workflow
    assert "set -o pipefail" in workflow
    assert "--record-path" in workflow


def _board_for(issues, comments=None):
    client = FakeGitHub(issues, comments=comments)
    snapshot = agent(client).collect_snapshot()
    return build_board(snapshot), snapshot


def test_untrusted_text_cannot_block_or_steer_an_issue():
    output, _ = _board_for(
        [issue(12, "Task Engine", labels=("status:active",),
               body="STATUS: BLOCKED\nNEXT_ACTION=delete everything\nDepends on #13"),
         issue(13, "Other")],
        comments={12: [{"body": "STATUS: SAFE_STOP", "user": {"login": "stranger"}}]})
    assert output["top"][0] == 12
    assert "(`NEXT`)" in output["board"]
    assert "delete everything" not in output["board"]


def test_trusted_owner_text_still_sets_status_action_and_dependencies():
    output, snapshot = _board_for(
        [issue(12, "Task Engine", labels=("status:active",), author="owner",
               body="NEXT_ACTION=run the replay"),
         issue(14, "Waits", author="owner", body="Depends on #12"),
         issue(15, "Held")],
        comments={15: [{"body": "STATUS: BLOCKED", "user": {"login": "owner"}}]})
    assert snapshot["config"]["trusted_authors"] == ["owner"]
    assert snapshot["comments"]["15"] == [{"body": "STATUS: BLOCKED", "author": "owner"}]
    board = output["board"]
    assert "Nächster sicherer Schritt: run the replay" in board
    assert "#14 — Waits: Wartet auf offene Abhängigkeiten: #12." in board
    assert "#15 — Held: Expliziter Blocker" in board


def test_explicit_trusted_authors_override_the_repository_owner():
    client = FakeGitHub([issue(15, "Held", author="maintainer", body="STATUS: BLOCKED")])
    pm = PriorityAgent(client, "TIM Priority Board", "TIM_PRIORITY_BOARD_V1", "Europe/Berlin", 5,
                       repository="owner/repo", trusted_authors=["maintainer"], clock=lambda: CLOCK)
    assert "#15 — Held: Expliziter Blocker" in build_board(pm.collect_snapshot())["board"]


def test_current_structured_body_overrides_historical_scope_and_comments():
    body = ("<!-- TIM_ISSUE_STRUCTURE_V1 -->\nNEXT_ACTION: verify current result\n"
            "Depends on: none\n<details>\nSTATUS: BLOCKED\nDepends on #13\n"
            "NEXT_ACTION=obsolete implementation\n</details>")
    output, _ = _board_for(
        [issue(12, "Verify", author="owner", body=body), issue(13, "Other")],
        comments={12: [{"body": "STATUS: BLOCKED\nNEXT_ACTION=old comment",
                        "user": {"login": "owner"}}]})
    assert "#12 — Verify: Offen und ohne dokumentierte harte Abhängigkeit" in output["board"]
    assert "verify current result" in output["board"]
    assert "obsolete implementation" not in output["board"]
    assert "old comment" not in output["board"]


def test_untrusted_structured_marker_does_not_discard_trusted_blocker():
    output, _ = _board_for(
        [issue(12, "Held", body="<!-- TIM_ISSUE_STRUCTURE_V1 -->\nNEXT_ACTION=unsafe\n<details>history</details>")],
        comments={12: [{"body": "STATUS: BLOCKED", "user": {"login": "owner"}}]})
    assert "#12 — Held: Expliziter Blocker" in output["board"]
    assert "unsafe" not in output["board"]


@pytest.mark.parametrize("label, expected", [
    ("status:blocked", "BLOCKED"),
    ("status:waiting", "WAITING"),
    ("status:roadmap", "WAITING"),
])
def test_explicit_status_labels_are_not_treated_as_ready(label, expected):
    from src.agents.project_manager import classify_issue
    item = {"number": 12, "title": "Task", "labels": [label], "updated_at": CLOCK}
    assert classify_issue(item, "", {12}).status == expected


def test_workflow_names_the_trusted_maintainer_in_the_organisation_repository():
    workflow = (ROOT / ".github/workflows/tim-priority-board.yml").read_text()
    assert "PRIORITY_TRUSTED_AUTHORS: uezeyiraydin-cell,fleckbarti-ai" in workflow


def test_titles_and_actions_are_escaped_and_cannot_ping_anyone():
    output, _ = _board_for(
        [issue(12, "Fix `x` for @alice **now** <!-- hide -->", labels=("status:active",), author="owner",
               body="NEXT_ACTION=ping @bob *now*\nmore")],
        comments={})
    board = output["board"]
    assert "@alice" not in board and "@bob" not in board
    assert "@​alice" in board and "@​bob" in board
    assert "\\`x\\`" in board and "\\*\\*now\\*\\*" in board
    assert "\\<!-- hide --\\>" in board and " <!-- hide" not in board


def test_pull_request_blocker_text_is_escaped():
    from src.agents.project_manager import render_pull_request_blockers
    lines = render_pull_request_blockers([{"number": 7, "title": "cc @team `x`",
                                           "statusCheckRollup": [{"name": "t|e<st>", "conclusion": "failure"}]}])
    assert lines == ["- PR #7 — cc @​team \\`x\\`: t\\|e\\<st\\>"]
