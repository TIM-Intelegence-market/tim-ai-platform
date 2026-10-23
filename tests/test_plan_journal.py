"""Paper journal of the Setup-Pfad plans (long/short) and its outcome rules."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.dashboard import plan_journal as pj
from src.dashboard.pages.plan_journal import _plan_journal_page, journal_note

T0 = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)  # Saturday night: no NY-open block


def _plan(direction: str = "LONG", entry: float = 100.0, stop: float = 99.0, invalid: float = 99.5) -> dict:
    risk = abs(entry - stop)
    sign = 1 if direction == "LONG" else -1
    return {
        "scenario_id": "B", "direction": direction, "entry_model": "RECLAIM", "plan_text": f"PLAN B {direction}",
        "entry_low": entry, "entry_high": entry + sign * 0.5, "entry": entry, "stop": stop,
        "targets": [entry + sign * risk * r for r in (1.5, 2.0, 3.0)],
        "invalidation_level": invalid, "invalidation_side": "<" if direction == "LONG" else ">",
        "scenario_state": "WATCH", "score": 0.5, "missing_confirmations": [], "decision": "NO_TRADE", "market_state": "RANGE",
    }


def _m(minute: int, low: float, high: float, close: float | None = None) -> dict:
    opened = T0 + timedelta(minutes=minute)
    close = (low + high) / 2 if close is None else close
    return {"timeframe": "1m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(seconds=59.999)).isoformat(),
            "open": close, "high": high, "low": low, "close": close, "volume": 1.0}


def _journal_with(plan: dict) -> dict:
    journal = pj.empty_journal()
    pj.record_plans(journal, [plan], T0 - timedelta(milliseconds=1))
    return journal


def test_long_fill_then_tp1_then_break_even_books_a_third_of_1_5_r() -> None:
    journal = _journal_with(_plan())
    candles = [_m(0, 100.2, 100.8), _m(1, 99.9, 100.3), _m(2, 100.2, 101.6), _m(3, 99.95, 100.4)]
    pj.evaluate(journal, candles, [], T0 + timedelta(minutes=5))
    entry = journal["entries"][0]
    assert entry["status"] == "CLOSED" and entry["exit_reason"] == "BREAK_EVEN"
    assert len(entry["tp_hits"]) == 1
    assert entry["result_r"] == 0.5


def test_stop_before_target_is_minus_one_r_and_stop_wins_a_shared_candle() -> None:
    journal = _journal_with(_plan())
    pj.evaluate(journal, [_m(0, 99.9, 100.2), _m(1, 98.9, 101.6)], [], T0 + timedelta(minutes=3))
    entry = journal["entries"][0]
    assert entry["exit_reason"] == "STOP" and entry["result_r"] == -1.0


def test_all_three_targets_give_plus_2_17_r_and_short_mirrors_long() -> None:
    journal = _journal_with(_plan("SHORT", entry=100.0, stop=101.0, invalid=100.5))
    pj.evaluate(journal, [_m(0, 99.8, 100.1), _m(1, 96.9, 99.9)], [], T0 + timedelta(minutes=3))
    entry = journal["entries"][0]
    assert entry["exit_reason"] == "TP3" and entry["result_r"] == round(0.5 + 2 / 3 + 1.0, 3)


def _q(index: int, low: float, high: float, close: float) -> dict:
    opened = T0 + timedelta(minutes=15 * index)
    return {"timeframe": "15m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=14, seconds=59.999)).isoformat(),
            "open": high, "high": high, "low": low, "close": close, "volume": 1.0}


def test_15m_close_beyond_invalidation_ends_the_plan_before_and_after_fill() -> None:
    # Short with entry far above: the 15m close above the level comes first.
    journal = _journal_with(_plan("SHORT", entry=103.0, stop=104.0, invalid=101.0))
    minutes = [_m(i, 100.5, 101.5, 101.4) for i in range(15)] + [_m(15, 101.2, 101.6)]
    pj.evaluate(journal, minutes, [_q(0, 100.5, 101.5, 101.4)], T0 + timedelta(minutes=17))
    assert journal["entries"][0]["status"] == "INVALIDATED"
    # Long filled, then a 15m close below the level closes the rest there.
    journal = _journal_with(_plan())
    minutes = [_m(0, 99.95, 100.3)] + [_m(i, 99.6, 99.9, 99.7) for i in range(1, 15)] + [_m(15, 99.4, 99.6)]
    pj.evaluate(journal, minutes, [_q(0, 99.4, 100.3, 99.45)], T0 + timedelta(minutes=17))
    entry = journal["entries"][0]
    assert entry["exit_reason"] == "INVALIDATION" and entry["result_r"] == -0.55


def test_no_entry_inside_the_ny_open_block() -> None:
    weekday_open = datetime(2026, 10, 23, 13, 30, tzinfo=timezone.utc)  # 9:30 New York
    journal = pj.empty_journal()
    pj.record_plans(journal, [_plan()], weekday_open - timedelta(minutes=10))
    inside = {"timeframe": "1m", "open_time": weekday_open.isoformat(), "close_time": (weekday_open + timedelta(seconds=59)).isoformat(),
              "open": 100.0, "high": 100.2, "low": 99.9, "close": 100.0, "volume": 1.0}
    pj.evaluate(journal, [inside], [], weekday_open + timedelta(minutes=2))
    assert journal["entries"][0]["status"] == "OPEN"


def test_new_levels_replace_the_open_plan_and_same_levels_do_not_duplicate() -> None:
    journal = _journal_with(_plan())
    assert pj.record_plans(journal, [_plan()], T0 + timedelta(minutes=15)) == []
    assert len(journal["entries"]) == 1
    added = pj.record_plans(journal, [_plan(entry=100.5, stop=99.5)], T0 + timedelta(minutes=30))
    assert len(added) == 1 and journal["entries"][0]["status"] == "REPLACED"
    # A direction TIM stops showing stays open like a resting limit.
    assert pj.record_plans(journal, [], T0 + timedelta(minutes=45)) == []
    assert journal["entries"][1]["status"] == "OPEN"
    # While a long is in the trade, no second long is opened.
    journal["entries"][1]["status"] = "FILLED"
    assert pj.record_plans(journal, [_plan(entry=101.0, stop=100.0)], T0 + timedelta(minutes=60)) == []


def test_pending_plan_expires_after_24_hours() -> None:
    journal = _journal_with(_plan())
    late = _m(24 * 60 + 1, 100.5, 100.9)
    pj.evaluate(journal, [late], [], T0 + timedelta(hours=25))
    entry = journal["entries"][0]
    assert entry["status"] == "EXPIRED" and "data_gap" in entry


def test_plans_from_model_keeps_only_complete_long_and_short_plans() -> None:
    good = {"id": "B", "direction": "LONG", "plan_text": "PLAN B LONG", "entry_low": 100, "entry_high": 100.5,
            "invalidation_level": {"level": 99.5, "side": "<"}, "preview": {"entry": 100.0, "stop": 99.0, "targets": [101.5, 102, 103]}}
    wrong_side = {**good, "preview": {"entry": 100.0, "stop": 101.0, "targets": [101.5, 102, 103]}}
    no_plan = {**good, "plan_text": None}
    neutral = {**good, "direction": "NEUTRAL"}
    plans = pj.plans_from_model({"analysis": {"decision": {"status": "NO_TRADE"}, "scenarios": [good, wrong_side, no_plan, neutral]}})
    assert [p["direction"] for p in plans] == ["LONG"] and plans[0]["invalidation_side"] == "<"


def test_update_runs_tim_pipeline_on_closed_15m_candles_and_saves(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series: dict[str, list[dict]] = {"15m": [], "1m": []}
    price = 100_000.0
    for i in range(90):
        opened = start + timedelta(minutes=15 * i)
        swing = 400 if (i // 10) % 2 else -400
        close = price + swing
        series["15m"].append({"timeframe": "15m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=14, seconds=59.999)).isoformat(),
                              "open": price, "high": max(price, close) + 50, "low": min(price, close) - 50, "close": close, "volume": 10.0})
        price = close
    path = tmp_path / "journal.json"
    now = start + timedelta(minutes=15 * 90)
    journal = pj.update(path, series, now)
    stored = json.loads(path.read_text())
    assert stored["last_plan_candle"] is not None and stored["schema"] == pj.SCHEMA
    again = pj.update(path, series, now + timedelta(minutes=1))
    assert len(again["entries"]) == len(journal["entries"])  # same 15m close: nothing new


def test_journal_page_lists_plans_in_local_time_and_sums_r() -> None:
    journal = _journal_with(_plan())
    pj.evaluate(journal, [_m(0, 99.9, 100.2), _m(1, 98.9, 99.5)], [], T0 + timedelta(minutes=3))
    pj.record_plans(journal, [_plan("SHORT", 101.0, 102.0, 101.5)], T0 + timedelta(minutes=15))
    page = _plan_journal_page({"operational_health": {}}, journal)
    assert "Plan-Journal" in page and "-1,00 R" in page
    assert "24.10. 03:59" in page  # 01:59 UTC = 03:59 MESZ
    assert "wartet auf Einstieg" in page
    assert "2 Pläne festgehalten" in journal_note(journal)
