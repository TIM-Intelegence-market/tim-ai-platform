"""Tests for the V2.9 shadow (src/tim_v2/shadow.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.tim_v2 import shadow

T0 = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def iso(m: int) -> str:
    return (T0 + timedelta(minutes=m)).isoformat().replace("+00:00", "Z")


def candle(m: int, o, h, l, c, tf_min=5):
    return {"open_time": iso(m), "close_time": iso(m + tf_min), "open": o, "high": h, "low": l, "close": c}


def bars(rows):
    return [{"t": iso(m), "o": str(o), "h": str(h), "l": str(l), "c": str(c)} for m, o, h, l, c in rows]


def plan(direction="LONG", entry=99, stop=95, created=6, **journal):
    return {"id": "p1", "direction": direction, "entry": entry, "stop": stop, "created_at": iso(created),
            "journal": {"status": journal.get("status", "OPEN"), "closed_at": journal.get("closed_at"),
                        "filled_at": journal.get("filled_at"), "net_r": journal.get("net_r")}}


def test_limit_entry_fills_and_journal_close_flattens():
    b = bars([(0, 100, 100, 100, 100), (5, 100, 100, 100, 100), (10, 100, 101, 98, 99),
              (15, 99, 103, 99, 102), (20, 104, 104, 104, 104)])
    out = shadow.simulate_plan(plan(status="CLOSED", closed_at=iso(16), filled_at=iso(11), net_r=0.7), b)
    assert out["order_type"] == "LIMIT"
    assert out["entry_fill_at"] == iso(10)
    assert out["state"] == "CLOSED" and out["exit_kinds"] == ["FLATTEN"]
    assert out["paper_net_r"] > 0
    assert out["orders_sent_to_exchange"] == 0


def test_stop_entry_and_stop_loss():
    b = bars([(0, 100, 100, 100, 100), (10, 100, 102, 100, 101), (15, 101, 101, 94, 95)])
    out = shadow.simulate_plan(plan(entry=101, stop=97, created=5), b)
    assert out["order_type"] == "STOP"
    assert out["state"] == "CLOSED" and out["exit_kinds"] == ["STOP_LOSS"]
    assert -1.3 < out["paper_net_r"] < -1.0  # one R plus costs


def test_no_look_ahead_bar_before_creation_does_not_fill():
    b = bars([(0, 100, 100, 90, 95), (5, 100, 100, 100, 100)])  # only the bar before creation touches 92
    out = shadow.simulate_plan(plan(entry=92, stop=88, created=3), b)
    assert out["state"] == "PENDING" and out["entry_fill_at"] is None


def test_expired_plan_is_cancelled():
    b = bars([(0, 100, 100, 100, 100), (5, 100, 101, 100, 100), (10, 100, 101, 100, 100), (15, 80, 80, 80, 80)])
    out = shadow.simulate_plan(plan(entry=99, stop=95, created=2, status="EXPIRED", closed_at=iso(12)), b)
    assert out["state"] == "CANCELLED"


@pytest.mark.parametrize("p,reason", [(plan(stop=101), "wrong side"), (plan(entry=None), "valid entry")])
def test_invalid_plans_are_skipped(p, reason):
    out = shadow.simulate_plan(p, bars([(0, 100, 100, 100, 100)]))
    assert out["state"] == "SKIPPED" and reason in out["reason"]


def test_waiting_without_earlier_bar():
    assert shadow.simulate_plan(plan(created=0), bars([(0, 100, 100, 100, 100)]))["state"] == "WAITING"


def test_kill_file_cancels(tmp_path):
    kill = tmp_path / "KILL"
    kill.write_text("x")
    b = bars([(0, 100, 100, 100, 100), (10, 100, 101, 98, 99)])
    out = shadow.simulate_plan(plan(), b, kill_file=kill)
    assert out["state"] == "REJECTED" and out["order_reason"] == "kill_switch_engaged"
    assert out["kill"][0]["source"] == "FILE"


def test_update_end_to_end(tmp_path, monkeypatch):
    journal = {"p1": {"id": "p1", "timeframe": "15m", "direction": "LONG", "entry": 99, "stop": 95,
                      "created_at": iso(6), "status": "FILLED", "filled_at": iso(11)}}

    def fake_load_view(path):
        return {"entries": list(journal.values())}

    import src.dashboard.plan_journal as pj
    monkeypatch.setattr(pj, "load_view", fake_load_view)
    series = {"5m": [candle(0, 100, 100, 100, 100), candle(5, 100, 100, 100, 100), candle(10, 100, 101, 98, 99),
                     candle(15, 99, 100, 99, 100)]}
    path = tmp_path / "shadow.json"
    state = shadow.update(path, [tmp_path / "j.json"], series, now=T0 - timedelta(minutes=1))
    state = shadow.update(path, [tmp_path / "j.json"], series, now=T0 + timedelta(minutes=21))
    rec = state["plans"]["j.json:p1"]
    assert rec["paper"]["state"] == "OPEN"
    assert state["summary"]["fill_agreement"] == 1.0
    assert state["isolation"]["ok"] and state["live_execution"] is False
    # bars are append-only and a later step with the same series adds nothing
    n = len(state["bars"])
    state = shadow.update(path, [tmp_path / "j.json"], series, now=T0 + timedelta(minutes=22))
    assert len(state["bars"]) == n
    assert json.loads(path.read_text())["summary"]["orders_sent_to_exchange"] == 0
    assert "0 Orders" in shadow.render_de(state)


def test_unclosed_bar_is_not_stored():
    rows = shadow._closed_bars({"5m": [candle(0, 1, 1, 1, 1), candle(5, 1, 1, 1, 1)]}, "5m", T0 + timedelta(minutes=7))
    assert [r["t"] for r in rows] == [iso(0)]
