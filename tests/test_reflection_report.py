import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.reflection import cli
from src.reflection.reader import load_export
from src.reflection.report import STATUS, build_report, iso_week_window, previous_iso_week, report_hash, to_json, to_markdown

FIXTURE = Path(__file__).parent / "fixtures" / "reflection" / "export.json"


def week_cases(week):
    start, end = iso_week_window(week)
    return load_export(FIXTURE, start, end)


def test_iso_week_window_and_previous_week():
    start, end = iso_week_window("2026-W48")
    assert start == datetime(2026, 11, 23, tzinfo=timezone.utc) and end - start == timedelta(days=7)
    assert previous_iso_week(datetime(2026, 11, 30, 6, tzinfo=timezone.utc)) == "2026-W48"
    assert previous_iso_week(datetime(2027, 1, 3, tzinfo=timezone.utc)) == "2026-W52"
    with pytest.raises(ValueError):
        iso_week_window("2026-48")


def test_report_is_deterministic_and_never_changes_rules():
    first = build_report("2026-W48", week_cases("2026-W48"), week_cases("2026-W47"), source="export")
    second = build_report("2026-W48", week_cases("2026-W48"), week_cases("2026-W47"), source="export")
    assert to_json(first) == to_json(second)
    assert first["report_hash"] == report_hash(first)
    assert first["automatic_rule_change"] is False
    proposal = first["proposal"]
    assert proposal["status"] == STATUS and proposal["automatic_rule_change"] is False
    assert STATUS in to_markdown(first)


def test_at_most_one_proposal_even_with_several_significant_rules():
    report = build_report("2026-W48", week_cases("2026-W48"), source="export")
    flagged = [rule for rule in report["rules"] if rule["significant_above"] or rule["significant_below"]]
    assert len(flagged) >= 2
    assert isinstance(report["proposal"], dict)


def test_no_proposal_without_data():
    report = build_report("2026-W40", [], source="export")
    assert report["proposal"] is None and "genug Fälle" in report["no_proposal_reason"]


def test_cases_outside_the_window_are_refused():
    with pytest.raises(ValueError):
        build_report("2026-W47", week_cases("2026-W48"), source="export")


def test_cli_check_and_write(tmp_path, capsys):
    assert cli.run(["--week", "2026-W48", "--input", str(FIXTURE), "--check"]) == 0
    assert capsys.readouterr().out.startswith("OK 2026-W48 cases=130")
    assert cli.run(["--week", "2026-W48", "--input", str(FIXTURE), "--out", str(tmp_path)]) == 0
    assert sorted(path.name for path in tmp_path.iterdir()) == ["reflection-2026-W48.json", "reflection-2026-W48.md"]
    data = json.loads((tmp_path / "reflection-2026-W48.json").read_text(encoding="utf-8"))
    assert data["previous_case_count"] == 130 and data["automatic_rule_change"] is False
