"""Paper journal of the Setup-Pfad plans (long/short), its outcome rules and the evidence gate."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dashboard import plan_journal as pj
from src.dashboard.chart_model import _time
from src.dashboard.pages.plan_journal import _plan_journal_page, journal_note
from src.research_lab.setup_evidence import DEFAULT_REGISTER_PATH, EVIDENCE_MAPPING_VERSION

T0 = datetime(2026, 10, 24, 2, 0, tzinfo=timezone.utc)  # Saturday night: no NY-open block
GRADE_A = {"setup_grade": "A", "grade_reasons": ["scenario_watching", "score_0.50", "rr_2.00", "no_conflicting_evidence"],
           "grade_ruleset_version": "grade/1.0.0", "graded_state": "WATCHING"}


def _plan(direction: str = "LONG", entry: float = 100.0, stop: float = 99.0, invalid: float = 99.5, grade: dict | None = None) -> dict:
    risk = abs(entry - stop)
    sign = 1 if direction == "LONG" else -1
    return {
        "scenario_id": "B", "scenario_type": "LIQUIDITY_SWEEP_REVERSAL", "direction": direction, "entry_model": "RECLAIM", "plan_text": f"PLAN B {direction}",
        "entry_low": entry, "entry_high": entry + sign * 0.5, "entry": entry, "stop": stop,
        "targets": [entry + sign * risk * r for r in (1.5, 2.0, 3.0)],
        "invalidation_level": invalid, "invalidation_side": "<" if direction == "LONG" else ">",
        "scenario_state": "WATCH", "score": 0.5, "missing_confirmations": [], "pipeline_decision": "NO_TRADE",
        "pipeline_decision_reasons": ["NO_SCENARIO_CONFIRMED"], "market_state": "RANGE", "grade": dict(GRADE_A if grade is None else grade),
        "symbol": "BTCUSDT", "venue": "BINANCE", "market_type": "SPOT", "data_quality": "PASS",
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
    # Entries recorded before be_cost/1 (no stop_rule) keep the old rule: stop to the entry after TP1.
    journal = _journal_with(_plan())
    journal["entries"][0].pop("stop_rule")
    candles = [_m(0, 100.2, 100.8), _m(1, 99.9, 100.3), _m(2, 100.2, 101.6), _m(3, 99.95, 100.4)]
    pj.evaluate(journal, candles, [], T0 + timedelta(minutes=5))
    entry = journal["entries"][0]
    assert entry["status"] == "CLOSED" and entry["exit_reason"] == "BREAK_EVEN"
    assert len(entry["tp_hits"]) == 1
    assert entry["gross_r"] == 0.5


def test_stop_before_target_is_minus_one_r_and_stop_wins_a_shared_candle() -> None:
    journal = _journal_with(_plan())
    pj.evaluate(journal, [_m(0, 99.9, 100.2), _m(1, 98.9, 101.6)], [], T0 + timedelta(minutes=3))
    entry = journal["entries"][0]
    assert entry["exit_reason"] == "STOP" and entry["gross_r"] == -1.0


def test_all_three_targets_give_plus_2_17_r_and_short_mirrors_long() -> None:
    journal = _journal_with(_plan("SHORT", entry=100.0, stop=101.0, invalid=100.5))
    pj.evaluate(journal, [_m(0, 99.8, 100.1), _m(1, 96.9, 99.9)], [], T0 + timedelta(minutes=3))
    entry = journal["entries"][0]
    assert entry["exit_reason"] == "TP3" and entry["gross_r"] == round(0.5 + 2 / 3 + 1.0, 3)


def _q(index: int, low: float, high: float, close: float) -> dict:
    opened = T0 + timedelta(minutes=30 * index)
    return {"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
            "open": high, "high": high, "low": low, "close": close, "volume": 1.0}


def test_30m_close_beyond_invalidation_ends_the_plan_before_and_after_fill() -> None:
    # Short with entry far above: the 30m close above the level comes first.
    journal = _journal_with(_plan("SHORT", entry=103.0, stop=104.0, invalid=101.0))
    minutes = [_m(i, 100.5, 101.5, 101.4) for i in range(30)] + [_m(30, 101.2, 101.6)]
    pj.evaluate(journal, minutes, [_q(0, 100.5, 101.5, 101.4)], T0 + timedelta(minutes=32))
    assert journal["entries"][0]["status"] == "INVALIDATED"
    # Long filled, then a 30m close below the level closes the rest there.
    journal = _journal_with(_plan())
    minutes = [_m(0, 99.95, 100.3)] + [_m(i, 99.6, 99.9, 99.7) for i in range(1, 30)] + [_m(30, 99.4, 99.6)]
    pj.evaluate(journal, minutes, [_q(0, 99.4, 100.3, 99.45)], T0 + timedelta(minutes=32))
    entry = journal["entries"][0]
    assert entry["exit_reason"] == "INVALIDATION" and entry["gross_r"] == -0.55


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
    assert pj.record_plans(journal, [_plan()], T0 + timedelta(minutes=30)) == []
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
    good = {"id": "B", "type": "LIQUIDITY_SWEEP_REVERSAL", "direction": "LONG", "plan_text": "PLAN B LONG", "entry_low": 100, "entry_high": 100.5,
            "invalidation_level": {"level": 99.5, "side": "<"}, "preview": {"entry": 100.0, "stop": 99.0, "targets": [101.5, 102, 103]}, "grade": GRADE_A}
    wrong_side = {**good, "preview": {"entry": 100.0, "stop": 101.0, "targets": [101.5, 102, 103]}}
    no_plan = {**good, "plan_text": None}
    neutral = {**good, "direction": "NEUTRAL"}
    plans = pj.plans_from_model({"analysis": {"decision": {"status": "NO_TRADE", "reasons": ["NO_SCENARIO_CONFIRMED"]}, "scenarios": [good, wrong_side, no_plan, neutral]}})
    assert [p["direction"] for p in plans] == ["LONG"] and plans[0]["invalidation_side"] == "<"
    assert plans[0]["scenario_type"] == "LIQUIDITY_SWEEP_REVERSAL" and plans[0]["grade"] == GRADE_A
    assert plans[0]["symbol"] is None and plans[0]["data_quality"] is None  # a model without market context stays unknown
    assert plans[0]["pipeline_decision"] == "NO_TRADE" and plans[0]["pipeline_decision_reasons"] == ["NO_SCENARIO_CONFIRMED"]


def test_update_runs_tim_pipeline_on_closed_30m_candles_and_saves(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series: dict[str, list[dict]] = {"30m": [], "1m": []}
    price = 100_000.0
    for i in range(90):
        opened = start + timedelta(minutes=30 * i)
        swing = 400 if (i // 10) % 2 else -400
        close = price + swing
        series["30m"].append({"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
                              "open": price, "high": max(price, close) + 50, "low": min(price, close) - 50, "close": close, "volume": 10.0})
        price = close
    path = tmp_path / "journal.json"
    now = start + timedelta(minutes=30 * 90)
    journal = pj.update(path, series, now)
    stored = json.loads(path.read_text())
    assert stored["last_plan_candle"] is not None and stored["schema"] == pj.SCHEMA
    again = pj.update(path, series, now + timedelta(minutes=1))
    assert len(again["entries"]) == len(journal["entries"])  # same 30m close: nothing new
    # Every recorded plan went through the evidence gate against the real register.
    assert stored["entries"], "the synthetic series must yield at least one plan"
    for entry in stored["entries"]:
        assert entry["journal_decision"] == "NO_TRADE" and entry["execution_status"] == "RESEARCH_ONLY"
        assert entry["evidence_status"] == "INSUFFICIENT_EVIDENCE"
        assert entry["evidence_ref"]["register_head_hash"] and entry["evidence_ref"]["variant_ids"] == []
        assert entry["evidence_ref"]["mapping_version"] == EVIDENCE_MAPPING_VERSION
        assert entry["setup_grade"] in {"A", "B", "C"} and entry["grade_ruleset_version"] == "grade/1.0.0"
        assert entry["graded_state"] != "CONFIRMED"  # the preview's forced confirmation is not graded
        assert entry["pipeline_decision"] == "NO_TRADE"
        assert entry["instrument"]["market_type"] == "SPOT" and entry["symbol"] == "BTCUSDT"
        if entry["direction"] == "SHORT":
            assert "short_not_executable_on_spot" in entry["journal_decision_reasons"]


def test_grade_a_plan_without_evidence_is_no_trade_research_only() -> None:
    journal = _journal_with(_plan())
    entry = journal["entries"][0]
    assert entry["setup_grade"] == "A"
    assert entry["evidence_status"] == "INSUFFICIENT_EVIDENCE" and entry["evidence_ref"]["reason"] == "EVIDENCE_NOT_EVALUATED"
    assert entry["execution_status"] == "RESEARCH_ONLY" and entry["journal_decision"] == "NO_TRADE"
    assert "evidence_not_evaluated" in entry["journal_decision_reasons"]
    assert "execution_research_only" in entry["journal_decision_reasons"]
    assert "pipeline_no_trade" in entry["journal_decision_reasons"] and "scenario_not_confirmed" in entry["journal_decision_reasons"]
    assert entry["pipeline_decision"] == "NO_TRADE"  # the pipeline's own decision is kept separately
    assert "decision" not in entry
    page = _plan_journal_page({"operational_health": {}}, journal)
    assert "kein empirischer Edge-Nachweis" in page and "NO_TRADE" in page and "Empfehlung" not in page.replace("keine Empfehlung", "")


def test_gate_stays_closed_even_with_passed_holdout_while_research_only() -> None:
    plan = {**_plan(grade={**GRADE_A, "graded_state": "CONFIRMED"}), "pipeline_decision": "TRADE_PLAN",
            "evidence_status": "PASSED_HOLDOUT", "evidence_ref": {"variant_ids": ["X"]}, "execution_status": "RESEARCH_ONLY"}
    decision, reasons = pj.journal_gate(plan)
    assert decision == "NO_TRADE" and reasons == ["execution_research_only"]
    # Only an explicit PAPER_APPROVED execution status, which nothing sets today, opens the gate.
    assert pj.journal_gate({**plan, "execution_status": "PAPER_APPROVED"}) == ("PAPER_TRADE", [])
    assert pj.journal_gate({**plan, "execution_status": "PAPER_APPROVED", "evidence_status": "NEGATIVE_EVIDENCE"})[1] == ["evidence_negative_evidence"]


def test_short_on_spot_unknown_instrument_and_bad_data_close_the_gate() -> None:
    open_plan = {**_plan(grade={**GRADE_A, "graded_state": "CONFIRMED"}), "pipeline_decision": "TRADE_PLAN",
                 "evidence_status": "PASSED_HOLDOUT", "evidence_ref": {"variant_ids": ["X"]}, "execution_status": "PAPER_APPROVED"}
    assert pj.journal_gate(open_plan) == ("PAPER_TRADE", [])
    short = {**open_plan, "direction": "SHORT"}
    assert pj.journal_gate(short)[1] == ["short_not_executable_on_spot"]
    assert pj.journal_gate({**open_plan, "market_type": "FUTURES"})[1] == ["instrument_unknown"]
    assert pj.journal_gate({**open_plan, "data_quality": "PARTIAL"})[1] == ["data_quality_partial"]
    assert pj.journal_gate({**open_plan, "data_quality": None})[1] == ["data_quality_unknown"]
    entry = _journal_with(_plan("SHORT", entry=100.0, stop=101.0, invalid=100.5))["entries"][0]
    assert "short_not_executable_on_spot" in entry["journal_decision_reasons"]
    assert entry["instrument"] == {"symbol": "BTCUSDT", "venue": "BINANCE", "market_type": "SPOT", "spec_version": "instrument/1",
                                   "tick_size": 0.01, "lot_step": 0.00001, "short_executable": False}


def test_fill_price_is_rounded_to_the_tick_against_the_plan() -> None:
    journal = _journal_with(_plan(entry=100.004, stop=99.0, invalid=98.5))
    pj.evaluate(journal, [_m(0, 99.9, 100.2), _m(1, 98.9, 100.1)], [], T0 + timedelta(minutes=3))
    entry = journal["entries"][0]
    assert entry["fill_price"] == 100.01  # a buy limit cannot fill below the next tick
    journal = _journal_with(_plan("SHORT", entry=100.004, stop=101.0, invalid=101.5))
    pj.evaluate(journal, [_m(0, 99.8, 100.1), _m(1, 99.9, 101.1)], [], T0 + timedelta(minutes=3))
    assert journal["entries"][0]["fill_price"] == 100.0
    assert pj.tick_fill({"entry": 100.004, "direction": "LONG", "instrument": None}) == 100.004


def test_stale_market_data_records_no_new_plans(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series = _series(start)
    path = tmp_path / "journal.json"
    late = start + timedelta(minutes=30 * 90) + pj.STALE_AFTER + timedelta(minutes=1)
    journal = pj.update(path, series, late)
    assert journal["entries"] == [] and journal["last_plan_candle"] is None
    assert len(journal["skipped"]) == 1 and journal["skipped"][0]["reason"] == "stale_data"
    assert len(pj.update(path, series, late + timedelta(minutes=1))["skipped"]) == 1  # noted once
    # Fresh data for a later close records again.
    opened = start + timedelta(minutes=30 * 90)
    series["30m"].append({"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
                          "open": series["30m"][-1]["close"], "high": series["30m"][-1]["close"] + 300, "low": series["30m"][-1]["close"] - 300,
                          "close": series["30m"][-1]["close"] + 200, "volume": 10.0})
    fresh = pj.update(path, series, opened + timedelta(minutes=31))
    assert fresh["last_plan_candle"] is not None


def test_decision_fields_never_change_after_the_outcome() -> None:
    journal = _journal_with(_plan())
    before = {k: journal["entries"][0][k] for k in pj.DECISION_FIELDS}
    pj.evaluate(journal, [_m(0, 99.9, 100.2), _m(1, 98.9, 101.6)], [], T0 + timedelta(minutes=3))
    entry = journal["entries"][0]
    assert entry["status"] == "CLOSED" and entry["gross_r"] == -1.0
    assert {k: entry[k] for k in pj.DECISION_FIELDS} == before
    # Replacement by new levels keeps the old entry's decision too.
    pj.record_plans(journal, [_plan(entry=100.5, stop=99.5)], T0 + timedelta(minutes=30))
    assert {k: entry[k] for k in pj.DECISION_FIELDS} == before


def test_with_evidence_uses_the_register_and_fails_closed(tmp_path: Path) -> None:
    plans = pj.with_evidence([_plan()], "30m", DEFAULT_REGISTER_PATH)
    assert plans[0]["evidence_status"] == "INSUFFICIENT_EVIDENCE" and plans[0]["evidence_ref"]["reason"] == "NO_EXPLICIT_RULE_EQUIVALENCE"
    assert plans[0]["evidence_ref"]["register_events"] > 0 and plans[0]["execution_status"] == "RESEARCH_ONLY"
    broken = tmp_path / "register.jsonl"
    broken.write_text('{"kind": "register", "variant": "X", "hypothesis": "H", "params": {}, "previous": "0", "protocol": "1.1", "hash": "bad"}\n')
    plans = pj.with_evidence([_plan()], "30m", broken)
    assert plans[0]["evidence_status"] == "INSUFFICIENT_EVIDENCE" and plans[0]["evidence_ref"]["reason"].startswith("REGISTER_UNREADABLE")
    journal = pj.empty_journal()
    pj.record_plans(journal, plans, T0)
    assert journal["entries"][0]["journal_decision"] == "NO_TRADE" and "evidence_insufficient_evidence" in journal["entries"][0]["journal_decision_reasons"]


def test_summary_counts_decisions_and_names_the_result_basis() -> None:
    journal = _journal_with(_plan())
    stats = pj.summary(journal)
    assert stats["no_trade"] == 1 and stats["paper_trades"] == 0 and stats["result_basis"] == "GROSS_R_AND_NET_R"
    assert stats["cost_model_version"] == "protocol/1.1" and stats["sum_net_r"] == 0.0


# --- costs (research protocol 1.1, section 4.3/4.4) -------------------------


def _closed(direction: str, candles: list[dict], entry: float = 100.0, stop: float | None = None, legacy: bool = False) -> dict:
    stop = stop if stop is not None else (99.0 if direction == "LONG" else 101.0)
    invalid = 98.0 if direction == "LONG" else 102.0
    journal = _journal_with(_plan(direction, entry=entry, stop=stop, invalid=invalid))
    if legacy:
        journal["entries"][0].pop("stop_rule")
    pj.evaluate(journal, candles, [], T0 + timedelta(minutes=len(candles) + 1))
    assert journal["entries"][0]["status"] == "CLOSED"
    return journal["entries"][0]


def test_stop_costs_fee_both_sides_and_stop_slippage_on_exit_long_and_short() -> None:
    long = _closed("LONG", [_m(0, 99.9, 100.2), _m(1, 98.9, 100.1)])
    short = _closed("SHORT", [_m(0, 99.8, 100.1), _m(1, 99.9, 101.1)])
    for entry in (long, short):
        assert entry["exit_reason"] == "STOP" and entry["gross_r"] == -1.0
        # fee 5 bp on 100 at entry and on the stop price; slippage 3 bp at entry, 5 bp (stop) at exit; / risk 1.0
        stop = entry["stop"]
        assert entry["fee_r"] == round((0.0005 * 100 + 0.0005 * stop) / 1.0, 4)
        assert entry["slippage_r"] == round((0.0003 * 100 + 0.0005 * stop) / 1.0, 4)
        assert entry["net_r"] == round(entry["gross_r"] - entry["fee_r"] - entry["slippage_r"], 4) < -1.0
        assert entry["cost_model_version"] == "protocol/1.1"
    # Mirror images: equal percentage costs give equal cost in R up to the stop-price difference.
    assert abs(long["fee_r"] - short["fee_r"]) < 0.0011 and abs(long["slippage_r"] - short["slippage_r"]) < 0.0011


def test_three_targets_charge_each_third_once_and_sum_to_one_exit() -> None:
    entry = _closed("LONG", [_m(0, 99.9, 100.2), _m(1, 100.0, 103.5)])
    assert entry["exit_reason"] == "TP3" and len(entry["tp_hits"]) == 3
    thirds = sum(0.0005 * target / 3 for target in (101.5, 102.0, 103.0))
    assert entry["fee_r"] == round(0.0005 * 100 + thirds, 4)
    assert entry["slippage_r"] == round(0.0003 * 100 + sum(0.0003 * target / 3 for target in (101.5, 102.0, 103.0)), 4)
    assert entry["net_r"] == round(entry["gross_r"] - entry["fee_r"] - entry["slippage_r"], 4)
    assert 0 < entry["net_r"] < entry["gross_r"]


def test_break_even_after_tp1_uses_stop_slippage_on_the_rest() -> None:
    entry = _closed("LONG", [_m(0, 100.2, 100.8), _m(1, 99.9, 100.3), _m(2, 100.2, 101.6), _m(3, 99.95, 100.4)], legacy=True)
    assert entry["exit_reason"] == "BREAK_EVEN" and entry["gross_r"] == 0.5
    rest = 2 / 3
    assert entry["slippage_r"] == round(0.0003 * 100 + 0.0003 * 101.5 / 3 + 0.0005 * 100 * rest, 4)
    assert entry["fee_r"] == round(0.0005 * 100 + 0.0005 * 101.5 / 3 + 0.0005 * 100 * rest, 4)
    assert entry["net_r"] < entry["gross_r"]


def test_tight_stops_make_the_same_percentage_costs_a_larger_cost_in_r() -> None:
    wide = _closed("LONG", [_m(0, 99.9, 100.2), _m(1, 98.9, 100.1)], stop=99.0)
    tight = _closed("LONG", [_m(0, 99.95, 100.2), _m(1, 99.4, 100.1)], stop=99.5)
    assert tight["gross_r"] == wide["gross_r"] == -1.0
    assert tight["fee_r"] > wide["fee_r"] and tight["slippage_r"] > wide["slippage_r"]


def test_costs_are_never_credits_and_unfilled_plans_carry_no_costs() -> None:
    journal = _journal_with(_plan())
    late = _m(24 * 60 + 1, 100.5, 100.9)
    pj.evaluate(journal, [late], [], T0 + timedelta(hours=25))
    entry = journal["entries"][0]
    assert entry["status"] == "EXPIRED" and entry["gross_r"] is None and entry["net_r"] is None
    for direction, candles in (("LONG", [_m(0, 99.9, 100.2), _m(1, 98.9, 100.1)]), ("SHORT", [_m(0, 99.8, 100.1), _m(1, 99.9, 101.1)])):
        closed = _closed(direction, candles)
        assert closed["fee_r"] > 0 and closed["slippage_r"] > 0


# --- append-only event log, replay and recovery ------------------------------


def _series(start: datetime, count: int = 90) -> dict[str, list[dict]]:
    series: dict[str, list[dict]] = {"30m": [], "1m": []}
    price = 100_000.0
    for i in range(count):
        opened = start + timedelta(minutes=30 * i)
        swing = 400 if (i // 10) % 2 else -400
        close = price + swing
        series["30m"].append({"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
                              "open": price, "high": max(price, close) + 50, "low": min(price, close) - 50, "close": close, "volume": 10.0})
        price = close
    return series


def _view(journal: dict) -> dict:
    return {k: v for k, v in journal.items() if k not in {"checked_at", "integrity", "log_seq", "log_head"}}


def test_replay_equals_saved_document_and_restart_is_idempotent(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series = _series(start)
    path = tmp_path / "journal.json"
    now = start + timedelta(minutes=30 * 90)
    journal = pj.update(path, series, now)
    events_path = pj.events_path_for(path)
    log = pj.journal_log.read(events_path)
    assert journal["entries"] and log.events
    kinds = [e["kind"] for e in log.events]
    assert kinds.count("PLAN_RECORDED") == len(journal["entries"]) and kinds.count("CANDLE_CLOSE_PROCESSED") == 1
    assert all(e["source_hash"] and e["recorded_at"] and e["hash"] and e["previous"] for e in log.events)
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert _view(pj.fold(log.events)) == _view(stored)
    # Restart with the same candles: nothing new in the log, same view.
    again = pj.update(path, series, now + timedelta(minutes=1))
    assert len(pj.journal_log.read(events_path).events) == len(log.events)
    assert _view(again) == _view(stored)
    # The view is lost: it comes back from the log alone, byte for byte in content.
    path.unlink()
    assert _view(pj.load(path)) == _view(stored) and pj.load(path)["integrity"] == "VIEW_FOLDED_FROM_LOG"
    rebuilt = pj.rebuild(path)
    assert _view(rebuilt) == _view(stored) and path.exists()
    # Following minutes plus the next 30m close (a checkpoint) produce PLAN_UPDATED events; the fold stays equal to the view.
    for i in range(30):
        opened = now + timedelta(minutes=i)
        series["1m"].append({"timeframe": "1m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(seconds=59.999)).isoformat(),
                             "open": 99_500.0, "high": 100_600.0, "low": 99_400.0, "close": 100_000.0, "volume": 1.0})
    series["30m"].append({"timeframe": "30m", "open_time": now.isoformat(), "close_time": (now + timedelta(minutes=29, seconds=59.999)).isoformat(),
                          "open": 99_500.0, "high": 100_600.0, "low": 99_400.0, "close": 100_000.0, "volume": 10.0})
    later = pj.update(path, series, now + timedelta(minutes=31))
    events = pj.journal_log.read(events_path).events
    assert any(e["kind"] == "PLAN_UPDATED" for e in events)
    assert _view(pj.fold(events)) == _view(json.loads(path.read_text(encoding="utf-8"))) == _view(later)
    assert len(pj.journal_log.read(events_path).events) == len(events)
    close_events = [e for e in events if e["kind"] == "CANDLE_CLOSE_PROCESSED"]
    expected = pj.journal_log.content_hash(pj.clean_candles(series["30m"], "30m")[-pj.PLAN_VISIBLE:])
    assert len(close_events) == 2 and close_events[-1]["source_hash"] == close_events[-1]["payload"]["source_hash"] == expected
    assert events[0]["kind"] == "PLAN_RECORDED" and events[0]["source_hash"] != close_events[0]["source_hash"]  # all candles vs. the 80 visible 30m


def test_cursor_only_progress_is_written_at_checkpoints_material_changes_at_once(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series = _series(start)
    path = tmp_path / "journal.json"
    now = start + timedelta(minutes=30 * 90)
    first = pj.update(path, series, now)
    events_path = pj.events_path_for(path)
    count = len(pj.journal_log.read(events_path).events)
    entry = first["entries"][0]
    far = entry["entry"] * (1.5 if entry["direction"] == "LONG" else 0.5)  # never touches entry or invalidation

    def minute(i: int, low: float, high: float) -> dict:
        opened = now + timedelta(minutes=i)
        return {"timeframe": "1m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(seconds=59.999)).isoformat(),
                "open": (low + high) / 2, "high": high, "low": low, "close": (low + high) / 2, "volume": 1.0}

    series["1m"] = []
    k = 0
    if not entry.get("armed", True):
        # A LONG limit above the close waits for the breakout: the arming 1m close is material, written at once.
        series["1m"] = [minute(0, entry["entry"] * 1.0005, entry["entry"] * 1.001)]
        armed = pj.update(path, series, now + timedelta(minutes=1))
        assert armed["entries"][0]["armed"] is True and armed["entries"][0]["status"] == "OPEN"
        count, k = count + 1, 1
        assert len(pj.journal_log.read(events_path).events) == count
        first = armed
    # Minutes without a fill: only evaluated_through moves; nothing is written, the view still advances.
    series["1m"] += [minute(k + i, far * 0.999, far * 1.001) for i in range(5)]
    step = pj.update(path, series, now + timedelta(minutes=k + 6))
    assert len(pj.journal_log.read(events_path).events) == count
    assert step["entries"][0]["evaluated_through"] == first["entries"][0]["evaluated_through"]  # the fold is the view
    # A fill is material: written at once, together with the cursor it was derived with.
    series["1m"].append(minute(k + 5, min(entry["entry"], far), max(entry["entry"], far)))
    filled = pj.update(path, series, now + timedelta(minutes=k + 7))
    events = pj.journal_log.read(events_path).events
    assert len(events) == count + 1 and events[-1]["kind"] == "PLAN_UPDATED"
    assert events[-1]["payload"]["changes"]["status"] == "FILLED" and "evaluated_through" in events[-1]["payload"]["changes"]
    assert filled["entries"][0]["status"] == "FILLED"
    # The next 30m close is a checkpoint: cursor-only progress since the fill is written then.
    series["1m"] += [minute(i, far * 0.999, far * 1.001) for i in range(k + 6, 31)]
    opened = now
    series["30m"].append({"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
                          "open": far, "high": far * 1.001, "low": far * 0.999, "close": far, "volume": 10.0})
    pj.update(path, series, now + timedelta(minutes=31))
    kinds = [e["kind"] for e in pj.journal_log.read(events_path).events[count + 1:]]
    assert "CANDLE_CLOSE_PROCESSED" in kinds and kinds.count("PLAN_UPDATED") >= 1


def test_load_checks_the_log_behind_a_valid_view(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    path = tmp_path / "journal.json"
    pj.update(path, _series(start), start + timedelta(minutes=30 * 90))
    events_path = pj.events_path_for(path)
    lines = events_path.read_text().splitlines()
    events_path.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(pj.journal_log.LogError):
        pj.load(path)
    assert pj.load_view(path)["blocked"] is True


def test_same_30m_close_with_other_candles_is_noted_not_rerecorded(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series = _series(start)
    path = tmp_path / "journal.json"
    now = start + timedelta(minutes=30 * 90)
    first = pj.update(path, series, now)
    revised = {"30m": [dict(c) for c in series["30m"]], "1m": []}
    revised["30m"][-1]["close"] += 10.0
    second = pj.update(path, revised, now + timedelta(seconds=30))
    assert second["entries"] == first["entries"] and second["last_plan_candle"] == first["last_plan_candle"]
    assert len(second["revisions"]) == 1
    revision = second["revisions"][0]
    assert revision["supersedes_source_hash"] == first["last_plan_candle_source_hash"] and revision["source_hash"] != revision["supersedes_source_hash"]
    # Offered again: no second revision event.
    third = pj.update(path, revised, now + timedelta(seconds=60))
    assert len(third["revisions"]) == 1


def test_fold_rejects_changes_to_decisions_and_events_after_close() -> None:
    journal = _journal_with(_plan())
    entry = journal["entries"][0]
    base = {"kind": "PLAN_RECORDED", "recorded_at": "x", "payload": {"entry": entry}}
    with pytest.raises(pj.journal_log.LogError):
        pj.fold([base, {"kind": "PLAN_UPDATED", "recorded_at": "x", "payload": {"id": entry["id"], "changes": {"journal_decision": "PAPER_TRADE"}}}])
    closed = {"kind": "PLAN_UPDATED", "recorded_at": "x", "payload": {"id": entry["id"], "changes": {"status": "CLOSED", "gross_r": -1.0}}}
    with pytest.raises(pj.journal_log.LogError):
        pj.fold([base, closed, {"kind": "PLAN_UPDATED", "recorded_at": "x", "payload": {"id": entry["id"], "changes": {"gross_r": 2.0}}}])
    with pytest.raises(pj.journal_log.LogError):
        pj.fold([base, base])
    with pytest.raises(pj.journal_log.LogError):
        pj.fold([{"kind": "PLAN_UPDATED", "recorded_at": "x", "payload": {"id": "nope", "changes": {}}}])


def test_broken_log_blocks_update_and_load_instead_of_an_empty_journal(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series = _series(start)
    path = tmp_path / "journal.json"
    pj.update(path, series, start + timedelta(minutes=30 * 90))
    events_path = pj.events_path_for(path)
    lines = events_path.read_text().splitlines()
    events_path.write_text("\n".join(lines[1:]) + "\n")  # first event deleted
    with pytest.raises(pj.journal_log.LogError):
        pj.update(path, series, start + timedelta(minutes=30 * 90 + 1))
    path.unlink()
    with pytest.raises(pj.journal_log.LogError):
        pj.load(path)


def test_view_anchor_detects_a_shortened_or_replaced_log(tmp_path: Path) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series = _series(start)
    path = tmp_path / "journal.json"
    journal = pj.update(path, series, start + timedelta(minutes=30 * 90))
    events_path = pj.events_path_for(path)
    assert journal["log_seq"] == len(pj.journal_log.read(events_path).events) and journal["log_head"]
    original = events_path.read_bytes()
    # Last valid event removed cleanly: the chain is intact, but shorter than the view remembers.
    lines = original.decode().splitlines()
    events_path.write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(pj.journal_log.LogError):
        pj.update(path, series, start + timedelta(minutes=30 * 90 + 1))
    # Same length, other history: the hash at the anchor differs.
    events_path.unlink()
    pj.journal_log.append(events_path, [{"event_id": f"x{i}", "kind": "CANDLE_REVISION_OBSERVED", "recorded_at": "x", "payload": {}} for i in range(len(lines))])
    with pytest.raises(pj.journal_log.LogError):
        pj.update(path, series, start + timedelta(minutes=30 * 90 + 1))
    # The genuine log again: continues.
    events_path.write_bytes(original)
    pj.update(path, series, start + timedelta(minutes=30 * 90 + 1))


def test_journal_page_lists_plans_in_local_time_and_sums_r() -> None:
    journal = _journal_with(_plan())
    pj.evaluate(journal, [_m(0, 99.9, 100.2), _m(1, 98.9, 99.5)], [], T0 + timedelta(minutes=3))
    pj.record_plans(journal, [_plan("SHORT", 101.0, 102.0, 101.5)], T0 + timedelta(minutes=30))
    page = _plan_journal_page({"operational_health": {}}, journal)
    assert "Plan-Journal" in page and "-1,00 R" in page and "Brutto-R" in page
    assert "24.10. 03:59" in page  # 01:59 UTC = 03:59 MESZ
    assert "wartet auf Einstieg" in page and "keine Evidenz" in page and "heuristisch" in page
    assert "Netto-R" in page and "protocol/1.1" in page and "append-only" in page
    assert "2 Pläne festgehalten" in journal_note(journal) and "2 × NO_TRADE" in journal_note(journal) and "netto" in journal_note(journal)


def test_broken_log_locks_the_page_and_the_api_view(tmp_path: Path) -> None:
    path = tmp_path / "journal.json"
    pj.events_path_for(path).write_text('{"not": "an event"}\n')
    view = pj.load_view(path)
    assert view["blocked"] is True and view["integrity"].startswith("LOG_BROKEN") and view["entries"] == []
    page = _plan_journal_page({"operational_health": {}}, view)
    assert "Journal gesperrt" in page and "GESPERRT" in page
    assert journal_note(view).startswith("Plan-Journal gesperrt")


def test_counter_trend_plans_are_marked_and_counted_not_hidden() -> None:
    assert pj.counter_trend("LONG", "TREND_DOWN") and pj.counter_trend("SHORT", "TREND_UP")
    assert not pj.counter_trend("LONG", "TREND_UP") and not pj.counter_trend("SHORT", "RANGE") and not pj.counter_trend("LONG", None)
    plan = {**_plan("LONG"), "market_state": "TREND_DOWN"}
    journal = _journal_with(plan)
    assert journal["entries"][0]["market_state"] == "TREND_DOWN"
    stats = pj.summary(journal)
    assert stats["counter_trend"] == {"plans": 1, "closed": 0, "sum_r": 0}
    page = _plan_journal_page({"operational_health": {}}, journal)
    assert "gegen den Trend (TREND_DOWN)" in page and "Gegen den Trend" in page
    assert "gegen den Trend (" not in _plan_journal_page({"operational_health": {}}, _journal_with(_plan("LONG")))


def test_plan_already_beyond_stop_or_invalidation_is_not_recorded() -> None:
    # 25.10.2026: LONG retest 82.143 with stop 81.732 while BTC closed near 80.900.
    long = _plan("LONG", entry=82_142.94, stop=81_732.23, invalid=82_060.88)
    assert "Stops" in pj.invalid_on_arrival(long, 80_900.0)
    assert "Ungültigkeitsmarke" in pj.invalid_on_arrival(long, 81_900.0)  # above the stop, below invalidation
    assert pj.invalid_on_arrival(long, 82_500.0) is None
    short = _plan("SHORT", entry=100.0, stop=101.0, invalid=100.5)
    assert pj.invalid_on_arrival(short, 101.2) and pj.invalid_on_arrival(short, 100.7)
    assert pj.invalid_on_arrival(short, 99.0) is None
    kept, dropped = pj.drop_invalid_on_arrival([long, _plan("LONG", entry=80_500.0, stop=80_000.0, invalid=80_200.0)], 80_900.0)
    assert [p["entry"] for p in kept] == [80_500.0] and kept[0]["close_at_record"] == 80_900.0 and len(dropped) == 1
    assert pj.drop_invalid_on_arrival([long], None) == ([long], [])


def test_update_drops_dead_plans_and_does_not_book_repeated_losses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series = _series(start)
    last_close = series["30m"][-1]["close"]
    dead = {**_plan("LONG", entry=last_close + 1_500, stop=last_close + 1_000, invalid=last_close + 1_100), "grade": None}
    monkeypatch.setattr(pj, "build_chart_model", lambda *a, **k: {"analysis": {}})
    monkeypatch.setattr(pj, "plans_from_model", lambda model: [dict(dead)])
    path = tmp_path / "journal.json"
    now = start + timedelta(minutes=30 * 90)
    journal = pj.update(path, series, now)
    assert journal["entries"] == []
    assert journal["structure_skips"] and any("jenseits des Stops" in r for r in journal["last_skips"])
    # The next close with the same dead plan again records nothing and books no loss.
    nxt = series["30m"][-1]
    opened = datetime.fromisoformat(nxt["open_time"]) + timedelta(minutes=30)
    series["30m"].append({**nxt, "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat()})
    again = pj.update(path, series, now + timedelta(minutes=30))
    assert again["entries"] == [] and pj.summary(again)["sum_net_r"] == 0.0
    assert pj.rebuild(path)["entries"] == []


def test_long_limit_above_the_close_waits_for_the_breakout_before_it_can_fill() -> None:
    plan = {**_plan("LONG", entry=100.0, stop=99.0, invalid=99.2), "close_at_record": 99.6}
    journal = _journal_with(plan)
    assert journal["entries"][0]["armed"] is False
    # Price trades through the entry from below without a close above it: no fill, not armed.
    pj.evaluate(journal, [_m(0, 99.5, 100.2, close=99.8)], [], T0 + timedelta(minutes=2))
    assert journal["entries"][0]["status"] == "OPEN" and journal["entries"][0]["armed"] is False
    # A 1m close above the entry arms the limit; that candle itself does not fill.
    pj.evaluate(journal, [_m(0, 99.5, 100.2, close=99.8), _m(1, 99.9, 100.6, close=100.4)], [], T0 + timedelta(minutes=3))
    entry = journal["entries"][0]
    assert entry["armed"] is True and entry["status"] == "OPEN" and entry["armed_at"]
    # The retest fills at the limit.
    pj.evaluate(journal, [_m(2, 99.95, 100.3, close=100.1)], [], T0 + timedelta(minutes=4))
    assert journal["entries"][0]["status"] == "FILLED"


def test_resting_limits_and_short_mirror_are_armed_or_wait_as_expected() -> None:
    assert pj._arming({**_plan("LONG", entry=100.0), "close_at_record": 100.5}) == {"armed": True}  # buy limit below market
    assert pj._arming({**_plan("SHORT", entry=100.0, stop=101.0, invalid=100.5), "close_at_record": 100.5}) == {"armed": False}
    assert pj._arming({**_plan("SHORT", entry=100.0, stop=101.0, invalid=100.5), "close_at_record": 99.5}) == {"armed": True}
    assert pj._arming(_plan("LONG")) == {}  # recorded without a close: legacy behaviour


# Stop rule be_cost/1 (Uzi, 25.10.2026): stop to break-even plus costs after TP1 and after some time in the trade.

def _rest_net_r(entry: dict, level: float) -> float:
    """Net R of the whole position closed at level on a stop, before any target."""
    risk = abs(entry["entry"] - entry["stop"])
    fill = entry.get("fill_price") or entry["entry"]
    move = level - fill if entry["direction"] == "LONG" else fill - level
    costs = (pj.FEE_PER_SIDE + pj.SLIPPAGE_PER_SIDE) * fill + (pj.FEE_PER_SIDE + pj.STOP_SLIPPAGE) * level
    return (move - costs) / risk


def test_new_entries_carry_the_cost_stop_rule() -> None:
    assert _journal_with(_plan())["entries"][0]["stop_rule"] == pj.STOP_RULE_COST


def test_cost_stop_level_closes_the_rest_at_net_zero_long_and_short() -> None:
    for direction, stop in (("LONG", 99.0), ("SHORT", 101.0)):
        entry = _journal_with(_plan(direction, stop=stop))["entries"][0]
        entry["fill_price"] = 100.0
        level = pj.cost_stop_level(entry)
        assert (level > 100.0) if direction == "LONG" else (level < 100.0)
        assert 0 <= _rest_net_r(entry, level) < 0.01  # covers the costs, rounded to the tick against us
    long_entry = _journal_with(_plan())["entries"][0]
    assert pj.cost_stop_level(long_entry) == 100.19  # 100 * 1.0008 / 0.999 = 100.1802 -> next tick up


def test_after_tp1_the_stop_sits_at_break_even_plus_costs() -> None:
    entry = _closed("LONG", [_m(0, 100.2, 100.8), _m(1, 99.9, 100.3), _m(2, 100.2, 101.6), _m(3, 99.95, 100.4)])
    assert entry["exit_reason"] == "BREAK_EVEN_COSTS" and entry["exit_price"] == 100.19
    assert entry["gross_r"] == round(1.5 / 3 + 2 / 3 * 0.19, 3)
    assert entry["net_r"] > 0
    # The same path under the old rule ends below zero after costs.
    old = _closed("LONG", [_m(0, 100.2, 100.8), _m(1, 99.9, 100.3), _m(2, 100.2, 101.6), _m(3, 99.95, 100.4)], legacy=True)
    assert entry["net_r"] > old["net_r"]


def _c30(k: int, low: float, high: float, close: float, start: datetime = T0) -> dict:
    opened = start + timedelta(minutes=30 * k)
    return {"timeframe": "30m", "open_time": opened, "close_time": opened + timedelta(minutes=29, seconds=59.999),
            "open": close, "high": high, "low": low, "close": close, "volume": 1.0}


def _filled(direction: str = "LONG", mfe: float = 0.0) -> dict:
    journal = _journal_with(_plan(direction, stop=99.0 if direction == "LONG" else 101.0, invalid=98.0 if direction == "LONG" else 102.0))
    fill = _m(0, 99.9, 100.3) if direction == "LONG" else _m(0, 99.7, 100.1)
    pj.evaluate(journal, [fill], [], T0 + timedelta(minutes=2))
    entry = journal["entries"][0]
    assert entry["status"] == "FILLED"
    entry["max_favorable_r"] = mfe
    return journal


QUIET = {"bos": [], "market_state": "RANGE", "scenarios": []}
LATER = T0 + timedelta(minutes=30)


def test_verdict_halten_while_the_thesis_is_intact_and_price_is_not_far_enough() -> None:
    entry = _filled()["entries"][0]
    assert pj.judge_trade(entry, QUIET, 100.25, LATER) == ("HALTEN", ["price_not_beyond_cost_level"])  # 100.25 < 100.19 + 0.1 R
    assert pj.judge_trade(entry, QUIET, 100.5, LATER) == ("HALTEN", ["thesis_intact"])


def test_verdict_sichern_on_structure_market_state_opposite_scenario_and_fallbacks() -> None:
    entry = _filled()["entries"][0]
    after, before = (T0 + timedelta(minutes=10)).isoformat(), (T0 - timedelta(hours=1)).isoformat()
    bos = {"bos": [{"kind": "BOS", "direction": "UP", "break_time": after}]}
    assert pj.judge_trade(entry, {**QUIET, **bos}, 100.5, LATER) == ("SICHERN", ["structure_confirms_bos"])
    old = {"bos": [{"kind": "BOS", "direction": "UP", "break_time": before}]}
    assert pj.judge_trade(entry, {**QUIET, **old}, 100.5, LATER)[0] == "HALTEN"  # a break before the fill is not earned by this trade
    mss = {"bos": [{"kind": "MSS", "direction": "DOWN", "break_time": after}]}
    assert pj.judge_trade(entry, {**QUIET, **mss}, 100.5, LATER) == ("SICHERN", ["structure_against_mss"])
    assert pj.judge_trade(entry, {**QUIET, "market_state": "TREND_DOWN"}, 100.5, LATER) == ("SICHERN", ["market_state_against"])
    opposite = {"scenarios": [{"direction": "SHORT", "state": "CONFIRMED"}, {"direction": "LONG", "state": "CONFIRMED"}]}
    assert pj.judge_trade(entry, {**QUIET, **opposite}, 100.5, LATER) == ("SICHERN", ["opposite_scenario_confirmed"])
    watching = {"scenarios": [{"direction": "SHORT", "state": "WATCHING"}]}
    assert pj.judge_trade(entry, {**QUIET, **watching}, 100.5, LATER)[0] == "HALTEN"
    assert pj.judge_trade(entry, QUIET, 100.5, T0 + timedelta(hours=pj.FALLBACK_HOURS)) == ("SICHERN", ["fallback_4h_in_trade"])
    entry["max_favorable_r"] = pj.FALLBACK_MFE_R
    assert pj.judge_trade(entry, QUIET, 100.5, LATER) == ("SICHERN", ["fallback_mfe_0.75r"])
    # Even with every reason, no move while price sits on the level.
    assert pj.judge_trade(entry, {**QUIET, **mss}, 100.2, LATER) == ("HALTEN", ["price_not_beyond_cost_level"])


def test_sichern_moves_the_stop_from_the_next_candle_and_books_net_zero() -> None:
    journal = _filled()
    entry = journal["entries"][0]
    pj.judge_trades(journal, {**QUIET, "market_state": "TREND_DOWN"}, [_c30(0, 99.9, 100.6, 100.5)])
    assert entry["tim_verdict"] == "SICHERN" and entry["tim_verdict_reasons"] == ["market_state_against"]
    assert entry["cost_stop"] == 100.19 and entry["cost_stop_kind"] == "BREAK_EVEN_COSTS" and entry["cost_stop_at"] == pj._iso(T0 + timedelta(minutes=29, seconds=59.999))
    pj.evaluate(journal, [_m(31, 100.1, 100.4)], [], T0 + timedelta(minutes=33))
    assert entry["status"] == "CLOSED" and entry["exit_reason"] == "COST_STOP" and entry["exit_price"] == 100.19
    assert 0 <= entry["net_r"] < 0.01
    assert entry["slippage_r"] == round(0.0003 * 100 + 0.0005 * 100.19, 4)  # stop execution


def test_halten_leaves_the_original_stop_and_is_judged_again_at_the_next_close() -> None:
    journal = _filled()
    entry = journal["entries"][0]
    pj.judge_trades(journal, QUIET, [_c30(0, 99.9, 100.6, 100.5)])
    assert entry["tim_verdict"] == "HALTEN" and "cost_stop" not in entry
    pj.evaluate(journal, [_m(31, 100.1, 100.4)], [], T0 + timedelta(minutes=33))
    assert entry["status"] == "FILLED"
    pj.judge_trades(journal, {**QUIET, "bos": [{"kind": "BOS", "direction": "UP", "break_time": (T0 + timedelta(minutes=40)).isoformat()}]},
                    [_c30(0, 99.9, 100.6, 100.5), _c30(1, 100.1, 100.7, 100.6)])
    assert entry["tim_verdict"] == "SICHERN" and entry["cost_stop"] == 100.19


def test_short_mirrors_the_verdict() -> None:
    journal = _filled("SHORT")
    entry = journal["entries"][0]
    pj.judge_trades(journal, {**QUIET, "market_state": "TREND_UP"}, [_c30(0, 99.4, 100.1, 99.5)])
    assert entry["cost_stop"] == pj.cost_stop_level(entry) < 100.0
    pj.evaluate(journal, [_m(31, 99.6, 99.9)], [], T0 + timedelta(minutes=33))
    assert entry["exit_reason"] == "COST_STOP" and entry["net_r"] >= 0


def test_entries_without_a_stop_rule_are_not_judged() -> None:
    journal = _filled()
    journal["entries"][0].pop("stop_rule")
    pj.judge_trades(journal, {**QUIET, "market_state": "TREND_DOWN"}, [_c30(0, 99.9, 100.6, 100.5)])
    assert "tim_verdict" not in journal["entries"][0] and "cost_stop" not in journal["entries"][0]


def test_protected_stop_trails_behind_confirmed_swing_lows_and_never_back() -> None:
    journal = _filled()
    entry = journal["entries"][0]
    entry.update(cost_stop=100.19, cost_stop_at=pj._iso(T0), cost_stop_kind="BREAK_EVEN_COSTS")
    # 30m candles since the fill: a swing low at 100.6 (k=3), confirmed two candles later.
    candles = [_c30(0, 99.9, 100.6, 100.5), _c30(1, 100.8, 101.0, 100.9), _c30(2, 100.9, 101.2, 101.0), _c30(3, 100.6, 101.3, 101.1),
               _c30(4, 100.9, 101.5, 101.4), _c30(5, 101.0, 101.6, 101.5)]
    pj.judge_trades(journal, QUIET, candles[:5])
    assert entry["cost_stop"] == 100.19  # the swing at k=3 is not confirmed yet (needs 2 candles after it)
    pj.judge_trades(journal, QUIET, candles)
    assert entry["cost_stop"] == 100.6 and entry["cost_stop_kind"] == "SWING"
    # A later, lower swing (k=6) never pulls the stop back; a higher one (k=10) trails further.
    more = candles + [_c30(6, 100.3, 101.7, 101.6), _c30(7, 100.8, 101.8, 101.7), _c30(8, 101.2, 101.9, 101.8)]
    pj.judge_trades(journal, QUIET, more)
    assert entry["cost_stop"] == 100.6
    higher = more + [_c30(9, 101.2, 102.0, 101.9), _c30(10, 101.1, 102.1, 102.0), _c30(11, 101.3, 102.4, 102.3), _c30(12, 101.5, 102.5, 102.4)]
    pj.judge_trades(journal, QUIET, higher)
    assert entry["cost_stop"] == 101.1
    pj.evaluate(journal, [_m(13 * 30, 101.0, 101.4)], [], T0 + timedelta(minutes=13 * 30 + 2))
    assert entry["exit_reason"] == "TRAIL_STOP" and entry["exit_price"] == 101.1 and entry["gross_r"] == 1.1


def test_after_tp1_the_stop_trails_as_well_and_a_swing_behind_the_cost_level_is_ignored() -> None:
    journal = _filled()
    entry = journal["entries"][0]
    pj.evaluate(journal, [_m(1, 100.2, 101.6)], [], T0 + timedelta(minutes=3))
    assert len(entry["tp_hits"]) == 1 and entry["status"] == "FILLED"
    candles = [_c30(0, 99.9, 101.6, 101.5), _c30(1, 101.2, 101.7, 101.6), _c30(2, 101.4, 101.8, 101.7), _c30(3, 101.0, 101.9, 101.8),
               _c30(4, 101.5, 102.0, 101.9), _c30(5, 101.6, 102.1, 102.0)]
    pj.judge_trades(journal, QUIET, candles)
    assert entry["cost_stop"] == 101.0 and entry["cost_stop_kind"] == "SWING"  # swing low k=3
    behind = candles + [_c30(6, 100.1, 102.2, 102.1), _c30(7, 101.3, 102.3, 102.2), _c30(8, 101.5, 102.4, 102.3)]
    pj.judge_trades(journal, QUIET, behind)
    assert entry["cost_stop"] == 101.0  # the swing at k=6 (100.1) lies behind the protected stop: ignored
    pj.evaluate(journal, [_m(9 * 30, 100.9, 101.5)], [], T0 + timedelta(minutes=9 * 30 + 2))
    assert entry["exit_reason"] == "TRAIL_STOP" and entry["gross_r"] == round(1.5 / 3 + 2 / 3 * 1.0, 3)


def test_update_judges_filled_plans_at_each_30m_close(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime(2026, 10, 24, 0, 0, tzinfo=timezone.utc)
    series: dict[str, list[dict]] = {"30m": [], "1m": []}
    price = 100.0
    for k in range(90):
        opened = start + timedelta(minutes=30 * k)
        series["30m"].append({"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
                              "open": price, "high": price + 0.3, "low": price - 0.3, "close": price, "volume": 1.0})
    now = start + timedelta(minutes=30 * 90)
    monkeypatch.setattr(pj, "build_chart_model", lambda *a, **k: {**QUIET, "market_state": "TREND_DOWN", "scenarios": []})
    monkeypatch.setattr(pj, "plans_from_model", lambda model: [])
    path = tmp_path / "journal.json"
    pj.update(path, series, now)
    # Inject a filled plan into the log the way a real fill would be stored, then let the next close judge it.
    journal = pj.load(path)
    plan = _plan(entry=99.8, stop=98.8, invalid=98.0)
    before = pj.deepcopy(journal)
    pj.record_plans(journal, [plan], now)
    entry = journal["entries"][-1]
    entry.update(status="FILLED", filled_at=pj._iso(now + timedelta(minutes=1)), fill_price=99.8, max_favorable_r=0.0, max_adverse_r=0.0)
    from src.dashboard import journal_log
    state = journal_log.read(pj.events_path_for(path))
    written = journal_log.append(pj.events_path_for(path), pj.diff_events(before, journal, recorded_at=now, source_hash="x", source_range={}), state)
    assert written
    pj.save({**pj.fold(state.events + written), "log_seq": len(state.events) + len(written), "log_head": written[-1]["hash"]}, path)
    opened = now
    series["30m"].append({"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
                          "open": 100.0, "high": 100.6, "low": 99.9, "close": 100.5, "volume": 1.0})
    result = pj.update(path, series, now + timedelta(minutes=31))
    judged = [e for e in result["entries"] if e["id"] == entry["id"]][0]
    assert judged["tim_verdict"] == "SICHERN" and judged["cost_stop"] == pj.cost_stop_level(judged)
    assert any(e["kind"] == "PLAN_UPDATED" and "tim_verdict" in e["payload"]["changes"] for e in journal_log.read(pj.events_path_for(path)).events)


def test_late_recorded_plan_does_not_trade_the_minutes_of_the_previous_stop() -> None:
    # 26.10.2026 level/1: the 13:00 close was processed at 13:04, after the previous trade
    # had been stopped at 13:03. The new plan must not "fill" and stop in those same minutes.
    journal = _journal_with(_plan())
    candles = [_m(0, 100.1, 100.4), _m(1, 99.9, 100.3), _m(2, 98.9, 99.8)]
    pj.evaluate(journal, candles, [], T0 + timedelta(minutes=4))
    first = journal["entries"][0]
    assert first["exit_reason"] == "STOP" and pj._time(first["closed_at"]) > T0 + timedelta(minutes=2)
    pj.record_plans(journal, [_plan()], T0)  # same 30m close, written late
    second = journal["entries"][1]
    assert second["status"] == "OPEN" and second["evaluated_through"] == first["closed_at"]
    pj.evaluate(journal, [*candles, _m(3, 100.1, 100.6)], [], T0 + timedelta(minutes=5))
    assert journal["entries"][1]["status"] == "OPEN" and journal["entries"][1].get("fill_price") is None
    # Later minutes still fill it.
    pj.evaluate(journal, [_m(4, 99.95, 100.3)], [], T0 + timedelta(minutes=6))
    assert journal["entries"][1]["status"] == "FILLED"
