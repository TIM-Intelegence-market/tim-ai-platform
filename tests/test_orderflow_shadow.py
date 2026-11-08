"""Orderflow-Schatten (src/dashboard/orderflow_shadow.py) and the Lage tile/section (src/dashboard/orderflow_tile.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.dashboard import orderflow_shadow as shadow
from src.dashboard import orderflow_tile as tile
from src.dashboard.plan_journal import SCHEMA

T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def lage(direction: str, strength: int = 2, exhaustion: bool = False, price: float = 75000.0, at: datetime = T0) -> dict:
    return {"schema": "orderflow-lage/1", "symbol": "BTCUSDT", "as_of": at.isoformat(), "price": price, "stale": False,
            "tempo": 1.8, "windows": {"1m": {"delta": 0.5}, "5m": {"delta": 3.0 if direction == "auf" else -3.0, "volume": 10.0}, "15m": {}},
            "wave": {"direction": direction, "strength": strength, "phase": "läuft", "exhaustion": exhaustion},
            "levels": [{"name": "Vortag VAL", "price": 74950.0, "distance_pct": -0.07, "bid": 10.0, "ask": 1.0, "delta": -9.0,
                        "imbalance": "Verkäufer", "absorption": True}],
            "perp": {"delta_5m": 20.0, "delta_15m": 25.0}, "text": "Preis 75000. Käuferwelle Stärke 2/3, Phase läuft."}


def write_journal(path, *entries) -> None:
    path.write_text(json.dumps({"schema": SCHEMA, "entries": [{**e, "symbol": "BTCUSDT"} for e in entries]}))


def plan(status: str = "OPEN", **extra) -> dict:
    base = {"id": "p1", "direction": "LONG", "timeframe": "15m", "created_at": T0.isoformat(), "entry": 75000.0, "stop": 74500.0,
            "targets": [75750.0, 76000.0, 76500.0], "status": status}
    return {**base, **extra}


def test_gate_and_exit_rules():
    assert shadow.gate("LONG", shadow.lage_view(lage("auf"))) == shadow.BESTAETIGT
    assert shadow.gate("LONG", shadow.lage_view(lage("auf", exhaustion=True))) == shadow.NEUTRAL
    assert shadow.gate("LONG", shadow.lage_view(lage("ab"))) == shadow.GEGEN
    assert shadow.gate("SHORT", shadow.lage_view(lage("ab"))) == shadow.BESTAETIGT
    assert shadow.gate("LONG", None) == shadow.NEUTRAL and shadow.gate("LONG", shadow.lage_view({"stale": True})) == shadow.NEUTRAL
    assert shadow.should_exit("LONG", shadow.lage_view(lage("ab", strength=1))) is None
    assert shadow.should_exit("LONG", shadow.lage_view(lage("ab", strength=2))) == "Gegenwelle"
    assert shadow.should_exit("LONG", shadow.lage_view(lage("auf", exhaustion=True))) == "Exhaustion"
    assert shadow.should_exit("SHORT", shadow.lage_view(lage("auf", strength=3))) == "Gegenwelle"


def test_r_of_uses_fill_and_costs():
    gross, net = shadow.r_of({"direction": "LONG", "fill_price": 100.0, "entry": 99.0, "stop": 90.0}, 120.0)
    assert gross == 2.0 and 1.9 < net < 2.0
    gross, _ = shadow.r_of({"direction": "SHORT", "entry": 100.0, "stop": 110.0}, 95.0)
    assert gross == 0.5
    assert shadow.r_of({"direction": "LONG", "entry": 100.0, "stop": 100.0}, 120.0) is None


def test_update_follows_a_plan_through_fill_exit_and_close(tmp_path):
    journal = tmp_path / "tim_plan_journal_short.json"
    path = tmp_path / "shadow.json"
    # 1. plan appears while the wave runs against it
    write_journal(journal, plan("OPEN"))
    state = shadow.update(path, [journal], lage("ab"), now=T0)
    record = state["plans"]["p1"]
    assert record["gate_at_plan"] == shadow.GEGEN and "gate_at_fill" not in record
    assert state["summary"]["plans"] == 1 and state["summary"]["closed"] == 0
    # 2. plan fills while the wave now runs with it
    t1 = T0 + timedelta(minutes=10)
    write_journal(journal, plan("FILLED", filled_at=t1.isoformat(), fill_price=75000.0))
    state = shadow.update(path, [journal], lage("auf", at=t1), now=t1)
    record = state["plans"]["p1"]
    assert record["gate_at_fill"] == shadow.BESTAETIGT and record["fill_price"] == 75000.0 and "of_exit" not in record
    # 3. a counter wave of strength 2 at 75300: the shadow leaves (+0.6 R gross)
    t2 = T0 + timedelta(minutes=25)
    state = shadow.update(path, [journal], lage("ab", strength=2, price=75300.0, at=t2), now=t2)
    exit_ = state["plans"]["p1"]["of_exit"]
    assert exit_["reason"] == "Gegenwelle" and exit_["price"] == 75300.0 and exit_["gross_r"] == 0.6 and exit_["net_r"] < 0.6
    # 4. later lage does not change the recorded exit; the journal closes at the stop
    t3 = T0 + timedelta(hours=2)
    write_journal(journal, plan("CLOSED", filled_at=t1.isoformat(), fill_price=75000.0, closed_at=t3.isoformat(),
                                exit_reason="STOP", exit_price=74500.0, net_r=-1.01))
    state = shadow.update(path, [journal], lage("ab", strength=3, price=74400.0, at=t3), now=t3)
    record = state["plans"]["p1"]
    assert record["of_exit"]["price"] == 75300.0 and record["journal"]["status"] == "CLOSED"
    s = state["summary"]
    assert s["closed"] == 1 and s["by_gate"][shadow.BESTAETIGT]["n"] == 1 and s["by_gate"][shadow.BESTAETIGT]["sum_net_r"] == -1.01
    assert s["of_exit"]["n"] == 1 and s["of_exit"]["sum_shadow_net_r"] > 0 > s["of_exit"]["sum_journal_net_r"]
    assert s["judgeable"] is False and shadow.load(path)["schema"] == shadow.SCHEMA


def test_update_skips_old_excluded_and_blocked(tmp_path):
    journal = tmp_path / "tim_plan_journal_mid.json"
    path = tmp_path / "shadow.json"
    old = plan("OPEN", id="old", created_at=(T0 - timedelta(days=1)).isoformat())
    excluded = plan("OPEN", id="ex", excluded=True)
    write_journal(journal, old, excluded, plan("OPEN", id="new"))
    state = shadow.update(path, [journal], None, now=T0)
    assert list(state["plans"]) == ["new"] and state["plans"]["new"]["gate_at_plan"] == shadow.NEUTRAL
    before = path.read_text()
    journal.write_text("{not json")  # a broken journal is skipped, the shadow keeps its plans
    state = shadow.update(path, [journal], lage("auf"), now=T0 + timedelta(minutes=1))
    assert list(state["plans"]) == ["new"] and before != path.read_text()


def test_tile_and_section():
    t = tile.tile(lage("auf"), now=T0 + timedelta(seconds=5))
    assert t.id == "orderflow" and t.value == "Käuferwelle 2/3, läuft" and t.state == "ok" and "Preis 75000" in t.detail
    stale = tile.tile({**lage("auf"), "stale": True}, now=T0)
    assert stale.state == "warn" and stale.value == "keine frischen Trades"
    assert tile.tile(None).state == "unknown"
    html = tile.section(lage("auf"))
    assert "Orderflow-Lage" in html and "Vortag VAL" in html and "Absorption" in html and "<script" not in html
    assert "noch keine Daten" in tile.section(None)
