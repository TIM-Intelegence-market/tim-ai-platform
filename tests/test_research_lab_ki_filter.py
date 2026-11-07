"""KI1 shadow filter: no look-ahead in the context, append-only hash-chained log, fair evaluation."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.research_lab.ki_filter import AUSLASSEN, NEHMEN
from src.research_lab.ki_filter.context import history_context, market_context, peers_context, plan_context
from src.research_lab.ki_filter.decide import (DECIDE_WINDOW, LogError, candidates, check_answer, read_log, run)
from src.research_lab.ki_filter.evaluate import MIN_TRADES, evaluate

UTC = timezone.utc
NOW = datetime(2026, 11, 7, 21, 5, tzinfo=UTC)
CREATED = "2026-11-07T21:00:00Z"


def plan(**extra):
    base = {"id": "p1", "timeframe": "15m", "direction": "LONG", "created_at": CREATED, "status": "OPEN",
            "entry": 100.0, "stop": 98.0, "targets": [103.0, 104.0, 106.0], "close_at_record": 101.0,
            "setup_grade": "B", "market_state": "TREND_UP", "symbol": "BTCUSDT"}
    base.update(extra)
    return base


def closed(pid, closed_at, net_r, **extra):
    return {"id": pid, "status": "CLOSED", "direction": "SHORT", "created_at": "2026-11-07T10:00:00Z",
            "filled_at": "2026-11-07T10:05:00Z", "closed_at": closed_at, "net_r": net_r, "gross_r": net_r + 0.1,
            "exit_reason": "TP3", **extra}


def test_plan_context_has_no_outcome_fields():
    entry = plan(filled_at="x", closed_at="y", gross_r=2.0, net_r=1.8, exit_reason="TP3", tim_verdict="SICHERN",
                 max_favorable_r=3.0, evidence_status="INSUFFICIENT_EVIDENCE", journal_decision="NO_TRADE",
                 pipeline_decision_reasons=["NO_SCENARIO_CONFIRMED"])
    ctx = plan_context(entry)
    for key in ("filled_at", "closed_at", "gross_r", "net_r", "exit_reason", "tim_verdict", "max_favorable_r", "status",
                "evidence_status", "journal_decision", "pipeline_decision_reasons"):
        assert key not in ctx
    assert ctx["targets_r"] == [1.5, 2.0, 3.0] and ctx["risk_pct"] == 2.0


def test_history_only_before_cutoff():
    cutoff = datetime(2026, 11, 7, 21, tzinfo=UTC)
    entries = [closed("a", "2026-11-07T20:00:00Z", 1.0), closed("b", "2026-11-07T21:00:00Z", -5.0),
               closed("c", "2026-11-07T22:00:00Z", 9.0), closed("d", "2026-11-07T19:00:00Z", 2.0, excluded=True)]
    history = history_context(entries, cutoff)
    assert history["closed_before"] == 1 and history["sum_net_r"] == 1.0


def test_market_drops_candles_closing_after_cutoff():
    cutoff = datetime(2026, 11, 7, 21, tzinfo=UTC)
    rows = [{"open_time": cutoff - timedelta(minutes=30), "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1, "delta": 1},
            {"open_time": cutoff - timedelta(minutes=15), "open": 2, "high": 3, "low": 2, "close": 3, "volume": 3, "delta": -1},
            {"open_time": cutoff - timedelta(minutes=5), "open": 3, "high": 9, "low": 3, "close": 9, "volume": 9, "delta": 5}]
    ctx = market_context(rows, cutoff, "15m")
    assert ctx["candles"] == 2 and ctx["high"] == 3 and ctx["cum_delta"] == 0
    assert market_context([], cutoff, "15m") == {"candles": 0}


def test_peers_never_show_later_plans_or_status():
    cutoff = datetime(2026, 11, 7, 21, tzinfo=UTC)
    peers = {"vp": [plan(id="v1", created_at="2026-11-07T20:30:00Z", status="CLOSED", net_r=3.0, closed_at="2026-11-07T22:00:00Z"),
                    plan(id="v2", created_at="2026-11-07T21:30:00Z")]}
    ctx = peers_context(peers, cutoff)["vp"]
    assert len(ctx["plans_last_24h"]) == 1 and "status" not in ctx["plans_last_24h"][0]
    assert ctx["closed_before"] == 0  # v1 closed after the cutoff


def test_candidates_window_and_state():
    entries = [plan(), plan(id="p2", status="FILLED"), plan(id="p3", filled_at=CREATED),
               plan(id="p4", created_at=(NOW - DECIDE_WINDOW - timedelta(minutes=1)).isoformat()), plan(id="p5")]
    assert [e["id"] for e in candidates(entries, {"p5"}, NOW)] == ["p1"]


def test_check_answer_rejects_bad_output():
    assert check_answer({"entscheidung": NEHMEN, "vertrauen": 0.7, "grund": "ok"})[0] == NEHMEN
    for bad in ({}, {"entscheidung": "KAUFEN", "vertrauen": 0.5}, {"entscheidung": NEHMEN, "vertrauen": 2},
                {"entscheidung": NEHMEN, "vertrauen": True}, "NEHMEN"):
        with pytest.raises(ValueError):
            check_answer(bad)


def test_run_writes_chain_once_and_hides_future(tmp_path: Path):
    log = tmp_path / "log.jsonl"
    future = closed("f", "2026-11-07T23:00:00Z", 7.77)
    views = {"15m": {"entries": [plan(), future]}}
    prompts = []

    def ask(prompt):
        prompts.append(prompt)
        return {"entscheidung": AUSLASSEN, "vertrauen": 0.4, "grund": "Delta gegen den Plan"}

    summary = run(views, {}, log, ask, "qwen-test", lambda s, tf, c: [], now=NOW)
    assert summary["decided"] == 1 and "7.77" not in prompts[0]
    again = run(views, {}, log, ask, "qwen-test", lambda s, tf, c: [], now=NOW)
    assert again["decided"] == 0
    records = read_log(log)
    assert len(records) == 1 and records[0]["decision"] == AUSLASSEN and records[0]["prev_hash"] is None


def test_failed_ask_writes_nothing(tmp_path: Path):
    log = tmp_path / "log.jsonl"

    def broken(prompt):
        raise TimeoutError

    summary = run({"15m": {"entries": [plan()]}}, {}, log, broken, "m", lambda s, tf, c: [], now=NOW)
    assert summary["failed"] == 1 and not log.exists()


def test_blocked_journal_is_skipped(tmp_path: Path):
    summary = run({"15m": {"blocked": True, "entries": [plan()]}}, {}, tmp_path / "l", lambda p: 1, "m",
                  lambda s, tf, c: [], now=NOW)
    assert summary["skipped_blocked"] == 1 and summary["decided"] == 0


def test_tampered_log_is_refused(tmp_path: Path):
    log = tmp_path / "log.jsonl"
    ask = lambda prompt: {"entscheidung": NEHMEN, "vertrauen": 0.9, "grund": "x"}
    run({"15m": {"entries": [plan(), plan(id="p2")]}}, {}, log, ask, "m", lambda s, tf, c: [], now=NOW)
    lines = log.read_text().splitlines()
    record = json.loads(lines[0])
    record["decision"] = AUSLASSEN
    log.write_text(json.dumps(record) + "\n" + lines[1] + "\n")  # head file unchanged
    with pytest.raises(LogError):
        read_log(log)
    log.write_text(lines[1] + "\n")  # first line removed
    with pytest.raises(LogError):
        read_log(log)


def test_evaluate_counts_only_timely_judgements():
    def rec(pid, decision, decided_at="2026-11-07T10:01:00Z"):
        return {"plan_id": pid, "timeframe": "15m", "decision": decision, "decided_at": decided_at,
                "model": "m", "prompt_version": "ki1-prompt/2"}
    entries = [closed("a", "2026-11-07T11:00:00Z", 2.0), closed("b", "2026-11-07T12:00:00Z", -1.0),
               closed("c", "2026-11-07T13:00:00Z", -1.0), closed("late", "2026-11-07T14:00:00Z", 5.0),
               {"id": "x", "status": "EXPIRED"}, {"id": "o", "status": "OPEN"}]
    records = [rec("a", NEHMEN), rec("b", AUSLASSEN), rec("c", NEHMEN), rec("late", NEHMEN, "2026-11-07T10:10:00Z"),
               rec("x", NEHMEN), rec("o", NEHMEN), rec("gone", NEHMEN)]
    result = evaluate(records, {"15m": {"entries": entries}})
    assert result["counts"] == {"judged": 7, "late": 1, "missing_plan": 1, "pending": 1, "no_fill": 1, "excluded": 0,
                                "other_model_or_prompt": 0, "duplicate": 0}
    assert result["rules_alone"]["sum_net_r"] == 0.0 and result["rules_alone"]["trades"] == 3
    assert result["rules_plus_ki"]["sum_net_r"] == 1.0 and result["ki_skipped"]["sum_net_r"] == -1.0
    assert result["rules_alone"]["max_drawdown_r"] == -2.0
    assert not result["ready"] and str(MIN_TRADES) in result["status"]


def test_written_at_and_context_and_head(tmp_path: Path):
    log = tmp_path / "log.jsonl"
    ask = lambda prompt: {"entscheidung": NEHMEN, "vertrauen": 0.9, "grund": "x"}
    later = NOW + timedelta(minutes=3)
    summary = run({"15m": {"entries": [plan()]}}, {}, log, ask, "m", lambda s, tf, c: [], now=NOW, clock=lambda: later)
    record = read_log(log)[0]
    assert record["written_at"] == "2026-11-07T21:08:00Z" and record["context"]["plan"]["id"] == "p1"
    assert summary["head"]["count"] == 1


def test_head_detects_cut_log_and_torn_line(tmp_path: Path):
    log = tmp_path / "log.jsonl"
    ask = lambda prompt: {"entscheidung": NEHMEN, "vertrauen": 0.9, "grund": "x"}
    run({"15m": {"entries": [plan(), plan(id="p2")]}}, {}, log, ask, "m", lambda s, tf, c: [], now=NOW)
    full = log.read_text()
    log.write_text(full.splitlines()[0] + "\n")  # chain still valid, but shorter than the head says
    with pytest.raises(LogError):
        read_log(log)
    log.write_text(full + '{"schema": "tim_ki')  # torn last line
    with pytest.raises(LogError):
        read_log(log)


def test_evaluate_dedupes_and_separates_models():
    entries = [closed("a", "2026-11-07T11:00:00Z", 2.0)]
    base = {"plan_id": "a", "timeframe": "15m", "decision": NEHMEN, "decided_at": "2026-11-07T10:01:00Z",
            "prompt_version": "ki1-prompt/2"}
    records = [{**base, "model": "qwen"}, {**base, "model": "qwen"}, {**base, "model": "other"}]
    result = evaluate(records, {"15m": {"entries": entries}}, model="qwen")
    assert result["rules_alone"]["trades"] == 1
    assert result["counts"]["duplicate"] == 1 and result["counts"]["other_model_or_prompt"] == 1
    late = {**base, "model": "qwen", "written_at": "2026-11-07T10:30:00Z"}
    assert evaluate([late], {"15m": {"entries": entries}})["counts"]["late"] == 1
