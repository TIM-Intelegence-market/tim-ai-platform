"""Reviewer-Pflicht für kritische Pfade (docs/MULTI_AGENTEN_SYSTEM.md, Paket P3)."""
import json

from src.agents.handover import SCHEMA
from src.agents.review_gate import check, critical_files, main


def _slip(**changes):
    data = {"schema": SCHEMA, "task_id": "github-pr-200", "issue_number": 200, "from_role": "REVIEWER",
            "to_role": "PM", "input": "Diff von PR #200", "output": "keine bestätigten Fehler",
            "evidence": [{"kind": "link", "ref": "PR #200 Kommentar Review"}], "attempt": 1, "max_attempts": 3,
            "gate": "F2_MERGE"}
    data.update(changes)
    return "Beschreibung\n\n```json TIM_HANDOVER_V1\n" + json.dumps(data) + "\n```\n"


def test_plain_change_needs_no_review():
    result = check(["src/dashboard/legend.py", "docs/x.md"], None)
    assert result.ok and result.critical == ()


def test_critical_paths_are_found():
    assert critical_files(["src/database/schema.py", "ops/launchd/a.plist", "src/dashboard/plan_journal.py",
                           "src/dashboard/plan_journal_view.py", "docs/research_lab/REGISTER.jsonl"]) == (
        "docs/research_lab/REGISTER.jsonl", "ops/launchd/a.plist", "src/dashboard/plan_journal.py", "src/database/schema.py")


def test_critical_change_without_slip_fails():
    result = check(["scripts/tim_watchdog.py"], "kein Zettel", 200)
    assert not result.ok and "ohne gültigen Reviewer-Zettel" in result.reason


def test_critical_change_with_reviewer_slip_passes():
    result = check(["src/research_lab/exit_variants.py"], _slip(), 200)
    assert result.ok and "PR #200 Kommentar Review" in result.reason


def test_slip_from_other_role_or_other_pr_fails():
    engineer = _slip(from_role="ENGINEER", to_role="TESTER")
    assert "nicht vom REVIEWER" in check([".github/workflows/ci.yml"], engineer, 200).reason
    assert "another issue" in check([".github/workflows/ci.yml"], _slip(), 201).reason


def test_cli(tmp_path, capsys):
    event, files = tmp_path / "event.json", tmp_path / "files.txt"
    files.write_text("src/database/x.py\n\n", encoding="utf-8")
    event.write_text(json.dumps({"pull_request": {"number": 200, "body": _slip()}}), encoding="utf-8")
    assert main(["--event", str(event), "--files", str(files)]) == 0
    assert "PASS" in capsys.readouterr().out
    event.write_text(json.dumps({"pull_request": {"number": 200, "body": None}}), encoding="utf-8")
    assert main(["--event", str(event), "--files", str(files)]) == 1
    assert "kritisch: src/database/x.py" in capsys.readouterr().out
    assert main(["--event", str(tmp_path / "fehlt.json"), "--files", str(files)]) == 1
