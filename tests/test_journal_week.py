"""Wochenzahlen für den journal-auswerter (docs/SUBAGENTEN_PLAN.md): nur lesen, ehrlich bei kleinen Zahlen."""

import json
from datetime import datetime, timezone

from src.dashboard import journal_week
from src.dashboard.plan_journal import SCHEMA

UNTIL = datetime(2026, 11, 15, 23, 0, tzinfo=timezone.utc)


def _entry(day: int, net_r: float | None, **extra):
    stamp = f"2026-11-{day:02d}T12:00:00Z"
    return {"status": "CLOSED" if net_r is not None else "OPEN", "net_r": net_r, "closed_at": stamp if net_r is not None else None,
            "created_at": stamp, **extra}


def test_max_drawdown_counts_from_the_highest_point():
    assert journal_week.max_drawdown([1.0, -2.0, 0.5, -1.0]) == 2.5
    assert journal_week.max_drawdown([-1.0, -1.0]) == 2.0
    assert journal_week.max_drawdown([]) == 0.0


def test_week_and_previous_week_are_separate_and_small_samples_get_no_verdict():
    journal = {"entries": [_entry(3, 2.0), _entry(10, 1.0), _entry(11, -1.0), _entry(12, None), _entry(13, 5.0, excluded=True)]}
    result = journal_week.journal_report(journal, UNTIL)
    assert result["week"]["closed"] == 2 and result["week"]["sum_net_r"] == 0.0 and result["week"]["wins"] == 1
    assert result["week"]["max_drawdown_r"] == 1.0 and result["week"]["days_without_close"] == 5
    assert result["previous_week"]["closed"] == 1 and result["change_sum_net_r"] == -2.0
    assert result["week"]["judgeable"] is False and result["all_time"]["closed"] == 3
    assert result["new_plans"] == 4


def test_empty_week_reports_none_not_zero_mean():
    week = journal_week.window_stats([], UNTIL.replace(day=8), UNTIL)
    assert week["closed"] == 0 and week["mean_net_r"] is None and week["hit_rate"] is None and week["days_without_close"] == 7


def test_blocked_journal_is_named_not_counted_as_empty():
    assert journal_week.journal_report({"blocked": True, "integrity": "LOG_BROKEN: x", "entries": []}, UNTIL) == {
        "readable": False, "integrity": "LOG_BROKEN: x"}


def test_cli_reads_files_and_writes_nothing(tmp_path, capsys):
    path = tmp_path / "journal.json"
    path.write_text(json.dumps({"schema": SCHEMA, "source": "test", "last_plan_candle": None, "entries": [_entry(14, 0.5)]}), encoding="utf-8")
    before = sorted(p.name for p in tmp_path.iterdir())
    missing = tmp_path / "fehlt.json"
    assert journal_week.main([str(path), str(missing), "--shadow", str(tmp_path / "kein_schatten.json"), "--until", UNTIL.isoformat()]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["journals"][str(path)]["week"]["closed"] == 1
    assert out["journals"][str(missing)] == {"readable": False, "integrity": "FILE_MISSING"}
    assert out["shadow"] == {"readable": False}
    assert sorted(p.name for p in tmp_path.iterdir()) == before


def test_cli_rejects_time_without_zone(tmp_path):
    assert journal_week.main([str(tmp_path / "x.json"), "--until", "2026-11-15T12:00:00"]) == 2


def test_broken_journal_without_log_is_named_not_empty(tmp_path):
    bad = tmp_path / "kaputt.json"
    bad.write_text("{nicht json", encoding="utf-8")
    wrong = tmp_path / "schema.json"
    wrong.write_text(json.dumps({"schema": "anderes/1", "entries": [_entry(14, 0.5)]}), encoding="utf-8")
    result = journal_week.report([bad, wrong], None, UNTIL)
    assert result["journals"][str(bad)] == {"readable": False, "integrity": "UNREADABLE_OR_WRONG_SCHEMA"}
    assert result["journals"][str(wrong)] == {"readable": False, "integrity": "UNREADABLE_OR_WRONG_SCHEMA"}
