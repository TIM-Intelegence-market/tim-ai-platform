"""Trade reflection: one record per closed paper trade, fixed lessons, hash chain, ideas from repeated patterns."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from src.research_lab.workshop.ideas import IdeaQueue
from src.research_lab.workshop.trade_reflection import (IDEA_MIN_TRADES, ReflectionError, ReflectionLog, propose_ideas,
                                                        reflect, reflect_journal)

AT = "2026-10-31T14:00:00Z"


def _trade(i: int, **extra) -> dict:
    trade = {"id": f"p{i:03d}", "status": "CLOSED", "direction": "LONG", "timeframe": "30m", "market_state": "RANGE",
             "gross_r": 0.5, "fee_r": 0.1, "slippage_r": 0.05, "net_r": 0.35, "max_favorable_r": 1.6,
             "max_adverse_r": -0.2, "exit_reason": "BREAK_EVEN_COSTS", "tp_hits": ["t"], "created_at": "2026-10-30T10:00:00Z",
             "closed_at": "2026-10-30T14:00:00Z"}
    trade.update(extra)
    return trade


def test_lessons_follow_the_facts() -> None:
    costs = reflect(_trade(1, gross_r=0.1, net_r=-0.05))
    assert "COSTS_ATE_PROFIT" in costs["lessons"] and costs["outcome"] == "loss"
    gave_back = reflect(_trade(2, gross_r=-1.0, net_r=-1.1, max_favorable_r=1.2, exit_reason="STOP", tp_hits=[]))
    assert gave_back["lessons"] == ["GAVE_BACK"]
    instant = reflect(_trade(3, gross_r=-1.0, net_r=-1.1, max_favorable_r=0.1, max_adverse_r=-1.0, exit_reason="STOP",
                             tp_hits=[], stop_review={"wick": True}, market_state="TREND_DOWN", data_gap="x"))
    assert instant["lessons"] == ["WRONG_AT_ONCE", "STOP_BY_WICK", "AGAINST_TREND", "DATA_GAP"]
    assert costs["known_at"] == "2026-10-30T14:00:00Z"
    late = reflect(_trade(5, stop_review={"wick": True, "checked_through": "2026-10-30T16:00:00Z"}))
    assert late["known_at"] == "2026-10-30T16:00:00Z"
    full = reflect(_trade(4, gross_r=2.17, net_r=2.0, exit_reason="TP3", tp_hits=["a", "b", "c"]))
    assert full["lessons"] == ["FULL_TARGET"] and full["outcome"] == "win"
    assert full["automatic_rule_change"] is False and "+2.00 R netto" in full["summary"]


def test_journal_is_only_read_and_each_trade_reflected_once(tmp_path: Path) -> None:
    journal = {"entries": [_trade(1), _trade(2, status="FILLED", net_r=None), _trade(3, excluded={"reason": "Phantom"})]}
    before = deepcopy(journal)
    log = ReflectionLog(tmp_path / "r.jsonl")
    assert [r["trade_id"] for r in reflect_journal(journal, log, name="tim", at=AT)] == ["p001"]
    assert journal == before
    assert reflect_journal(journal, log, name="tim", at=AT) == []
    journal["entries"].append(_trade(4))
    assert [r["trade_id"] for r in reflect_journal(journal, log, name="tim", at=AT)] == ["p004"]
    assert [r["trade_id"] for r in reflect_journal(journal, log, name="tim_short", at=AT)] == ["p001", "p004"]
    assert len(log.records()) == 4


def test_edited_record_breaks_the_chain(tmp_path: Path) -> None:
    log = ReflectionLog(tmp_path / "r.jsonl")
    reflect_journal({"entries": [_trade(1), _trade(2)]}, log, name="tim", at=AT)
    lines = log.path.read_text().splitlines()
    record = json.loads(lines[0])
    record["facts"]["net_r"] = 9.9
    lines[0] = json.dumps(record, sort_keys=True)
    log.path.write_text("\n".join(lines) + "\n")
    with pytest.raises(ReflectionError, match="Zeile 1"):
        log.records()


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    log = ReflectionLog(tmp_path / "r.jsonl")
    assert len(reflect_journal({"entries": [_trade(1)]}, log, name="tim", at=AT, write=False)) == 1
    assert not log.path.exists()


def test_repeated_loss_pattern_becomes_one_idea(tmp_path: Path) -> None:
    log = ReflectionLog(tmp_path / "r.jsonl")
    queue = IdeaQueue(tmp_path / "IDEEN.jsonl")
    few = [_trade(i, gross_r=0.1, net_r=-0.05, max_favorable_r=0.5) for i in range(IDEA_MIN_TRADES - 1)]
    reflect_journal({"entries": few}, log, name="tim", at=AT)
    assert propose_ideas(log.records(), queue, at=AT) == []
    reflect_journal({"entries": few + [_trade(99, gross_r=2.2, net_r=2.0, exit_reason="TP3")]}, log, name="tim", at=AT)
    added = propose_ideas(log.records(), queue, at=AT)
    assert added == ["I-0001"]  # COSTS_ATE_PROFIT in 19/20; FULL_TARGET never becomes an idea
    idea = queue.ideas()["I-0001"]
    assert idea["source"] == "trade_reflexion" and "19 von 20" in idea["hypothesis"]
    assert propose_ideas(log.records(), queue, at=AT) == []  # same pattern only once
