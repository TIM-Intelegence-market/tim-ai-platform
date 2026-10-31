"""F6 timetable: what is due when, CI and PAUSE hold it, the AI round stays inside the queue's limits."""
from __future__ import annotations

import json
import plistlib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.research_lab.workshop.ideas import IdeaQueue
from src.research_lab.workshop.schedule import Workshop, due_tasks, last_slot, parse_ki_answer, previous_month

ROOT = Path(__file__).resolve().parents[1]


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _trade(i: int) -> dict:
    return {"id": f"p{i:03d}", "status": "CLOSED", "direction": "LONG", "timeframe": "30m", "market_state": "RANGE",
            "gross_r": 0.1, "fee_r": 0.1, "slippage_r": 0.05, "net_r": -0.05, "max_favorable_r": 0.5,
            "max_adverse_r": -0.2, "exit_reason": "BREAK_EVEN_COSTS", "tp_hits": [], "created_at": "2026-10-30T10:00:00Z",
            "closed_at": "2026-10-30T14:00:00Z"}


def _workshop(tmp_path: Path, *, ps: str = "", ask=None) -> Workshop:
    (tmp_path / "docs/research_lab").mkdir(parents=True)
    (tmp_path / "docs/research_lab/LOGBUCH.json").write_text(json.dumps({"entries": [
        {"id": "S10", "title": "IB-Ausbruch 30m", "status": "failed", "lesson": "Gate"}]}), encoding="utf-8")
    workshop = Workshop(tmp_path, ask=ask, ps=lambda: ps)
    journals = {"tim_plan_journal": {"entries": [_trade(i) for i in range(25)]},
                "tim_plan_journal_short": {"entries": [_trade(1)]}}
    for name in journals:
        (tmp_path / "data/journal").mkdir(parents=True, exist_ok=True)
        (tmp_path / f"data/journal/{name}.json").write_text("{}", encoding="utf-8")
    workshop.load_journal = lambda path: journals[path.stem]
    return workshop


def test_slots_follow_local_time() -> None:
    # Sunday 1.11.2026 02:00 Berlin (winter time) = 01:00Z
    assert last_slot("weekly", _utc("2026-11-01T01:30:00Z")) == _utc("2026-11-01T01:00:00Z")
    assert last_slot("weekly", _utc("2026-11-08T00:30:00Z")) == _utc("2026-11-01T01:00:00Z")
    assert last_slot("monthly", _utc("2026-11-01T02:30:00Z")) == _utc("2026-11-01T02:00:00Z")
    assert last_slot("monthly", _utc("2026-11-01T01:30:00Z")) == _utc("2026-10-01T01:00:00Z")  # summer time
    assert previous_month(_utc("2026-11-01T02:30:00Z")) == "2026-10"
    assert previous_month(_utc("2026-10-31T23:30:00Z")) == "2026-10"  # already 1.11. locally


def test_due_tasks() -> None:
    now = _utc("2026-11-01T01:30:00Z")
    assert due_tasks({}, now) == ["trades", "weekly", "monthly"]
    state = {"trades": {"last_run": "2026-11-01T01:00:00Z"}, "weekly": {"last_run": "2026-11-01T01:10:00Z"},
             "monthly": {"last_run": "2026-10-01T05:00:00Z"}}
    assert due_tasks(state, now) == []
    assert due_tasks(state, _utc("2026-11-01T01:58:00Z")) == ["trades"]
    assert due_tasks(state, _utc("2026-11-01T02:30:00Z")) == ["trades", "monthly"]


def test_one_wakeup_writes_only_under_data_research(tmp_path: Path) -> None:
    workshop = _workshop(tmp_path)
    before = {p for p in tmp_path.rglob("*") if p.is_file()}
    summary = workshop.run_once(_utc("2026-11-01T02:30:00Z"))
    assert set(summary["ran"]) == {"trades", "weekly", "monthly"}
    assert all(r["ok"] for r in summary["ran"].values()), summary
    assert summary["ran"]["trades"]["new_reflections"] == {"tim_plan_journal": 25, "tim_plan_journal_short": 1}
    assert summary["ran"]["trades"]["ideas"]  # costs ate the profit in every trade -> one idea
    assert summary["ran"]["weekly"]["ki"] == "übersprungen"
    assert summary["ran"]["monthly"]["report"] == "data/research/reports/forschung_2026-10.md"
    new = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()} - {
        p.relative_to(tmp_path).as_posix() for p in before}
    assert new and all(p.startswith("data/research/") for p in new), new
    again = workshop.run_once(_utc("2026-11-01T02:45:00Z"))
    assert again["due"] == []


def test_ci_job_and_pause_hold_the_tasks(tmp_path: Path) -> None:
    workshop = _workshop(tmp_path, ps="/Users/timrunner/actions-runner/bin/Runner.Worker spawnclient 1 2")
    held = workshop.run_once(_utc("2026-11-01T02:30:00Z"))
    assert held["ran"]["trades"] == {"held": ["ci_test_job"]}
    assert not (tmp_path / "data/research/trade_reflections.jsonl").exists()
    late = workshop.run_once(_utc("2026-11-01T05:31:00Z"))  # after 3 h of waiting it runs anyway
    assert late["ran"]["trades"]["ok"] is True
    (tmp_path / "data/research/schedule/PAUSE").touch()
    assert workshop.run_once(_utc("2026-11-02T05:31:00Z"))["held"] == "PAUSE"


def test_dry_run_changes_nothing(tmp_path: Path) -> None:
    workshop = _workshop(tmp_path)
    summary = workshop.run_once(_utc("2026-11-01T02:30:00Z"), dry_run=True)
    assert summary["ran"]["weekly"] == {"would_run": True}
    assert not (tmp_path / "data/research").exists()


def test_ki_answer_is_untrusted() -> None:
    good = {"title": "Funding-Extrem", "hypothesis": "Nach extremem Funding dreht BTC", "data": ["archive_usdm_klines"],
            "template": "ereignis_studie", "period": ["2021-01-01", "2024-12-31"], "counterargument": "Zu selten", "tags": ["x"]}
    raw = "```json\n" + json.dumps({"ideas": [good, {**good, "data": ["geheim"]}, {**good, "counterargument": ""},
                                               {**good, "hypothesis": "x" * 500}, "Unsinn"]}) + "\n```"
    parsed = parse_ki_answer(raw)
    assert len(parsed) == 1 and parsed[0]["period"] == ("2021-01-01", "2024-12-31")
    assert parse_ki_answer("keine JSON-Antwort") == []


def test_ki_round_adds_at_most_three_ideas_and_checks_them(tmp_path: Path) -> None:
    def idea(n: int, period=("2021-01-01", "2024-12-31")) -> dict:
        return {"title": f"Idee {n} Wochenende", "hypothesis": f"Hypothese Nummer {n} über Wochenend-Volatilität {n}",
                "data": ["archive_spot_klines"], "template": "regel_backtest", "period": list(period),
                "counterargument": "Kosten", "tags": []}
    answer = json.dumps({"ideas": [idea(1), idea(2, ("2025-01-01", "2025-06-30")), idea(3), idea(4)]})
    prompts = []
    workshop = _workshop(tmp_path, ask=lambda prompt: prompts.append(prompt) or answer)
    result = workshop.run_once(_utc("2026-11-01T02:30:00Z"), only="weekly")["ran"]["weekly"]
    assert len(result["ki_ideas"]) == 3 and "Holdout" in prompts[0]
    ideas = IdeaQueue(tmp_path / "data/research/IDEEN.jsonl").ideas()
    statuses = {i["title"]: i["status"] for i in ideas.values() if i["source"] == "ki_runde"}
    assert statuses["Idee 2 Wochenende"] == "holdout_locked"
    assert "Idee 4 Wochenende" not in statuses
    assert (tmp_path / "data/research/ki_runde/2026-W44.json").exists()
    second = workshop.run_once(_utc("2026-11-01T03:30:00Z"), only="weekly")["ran"]["weekly"]
    assert second["ki"] == "Wochengrenze erreicht" and second["ki_ideas"] == []


def test_ki_failure_does_not_break_the_week(tmp_path: Path) -> None:
    def broken(prompt: str) -> str:
        raise FileNotFoundError("Claude Code CLI is unavailable")
    result = _workshop(tmp_path, ask=broken).run_once(_utc("2026-11-01T02:30:00Z"), only="weekly")["ran"]["weekly"]
    assert result["ok"] is True and result["ki"].startswith("Fehler: FileNotFoundError")


def test_launchd_template_is_background_and_niced() -> None:
    plist = plistlib.loads((ROOT / "ops/launchd/com.tim.research-workshop.plist").read_bytes())
    assert plist["ProcessType"] == "Background" and plist["Nice"] >= 10 and plist["LowPriorityIO"] is True
    assert plist["StartInterval"] == 900
    assert plist["ProgramArguments"][-1].endswith("scripts/research_workshop_schedule.py")
    assert plist["StandardOutPath"].startswith("/Users/tim/Documents/TIM/tim/data/research/")
