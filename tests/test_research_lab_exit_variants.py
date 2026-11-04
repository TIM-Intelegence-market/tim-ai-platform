"""Exit variants of the plan journal's last third (src/research_lab/exit_variants.py)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.research_lab import exit_variants as ev

T0 = datetime(2026, 11, 4, 0, 0, tzinfo=timezone.utc)


def minutes_through(points: list[float], start: datetime = T0, per_leg: int = 15) -> list[dict]:
    """1m candles moving linearly between ``points``, ``per_leg`` minutes per leg."""
    candles, price, moment = [], points[0], start
    for target in points[1:]:
        for step in range(per_leg):
            close = round(price + (target - price) / (per_leg - step), 6)
            candles.append({"open_time": moment, "close_time": moment + timedelta(minutes=1), "open": price,
                            "high": max(price, close) + 0.05, "low": min(price, close) - 0.05, "close": close})
            price, moment = close, moment + timedelta(minutes=1)
    return candles


# 15m bars as three 5-minute waypoints: fill near 100, TP1 115 / TP2 120, TP3 130, a pullback with a
# swing low at 134.5 (bar 9), a run to 150, then down to 118.
BARS = [(102, 105, 108), (110, 112, 113), (116, 119, 121), (123, 125, 126), (128, 131, 133), (134, 135, 136),
        (137, 138, 139), (138, 137, 137), (135, 134.5, 135.5), (136, 137, 138), (140, 141, 142), (144, 145, 146),
        (148, 149, 150), (149, 148, 147), (144, 142, 140), (136, 134, 132), (128, 126, 124), (121, 119, 118)]
PATH = [100] + [p for bar in BARS for p in bar]


def candles_for(path: list[float]) -> list[dict]:
    return minutes_through(path, per_leg=5)


def long_entry(candles: list[dict]) -> dict:
    tp1 = next(c for c in candles if c["high"] >= 115)["close_time"]
    tp2 = next(c for c in candles if c["high"] >= 120)["close_time"]
    return {"id": "x", "direction": "LONG", "timeframe": "15m", "entry": 100.0, "fill_price": 100.0, "stop": 90.0,
            "targets": [115.0, 120.0, 130.0], "filled_at": ev._iso(T0), "tp_hits": [ev._iso(tp1), ev._iso(tp2)],
            "status": "CLOSED", "exit_reason": "TP3", "exit_price": 130.0, "max_hold_hours": 24, "stop_rule": "be_cost/1"}


def run(variant: str, deltas: dict | None = None) -> dict:
    candles = candles_for(PATH)
    entry = long_entry(candles)
    return ev.follow_rest(entry, candles, ev.aggregate(candles, "15m"), ev.aggregate(candles, "1h"), variant, deltas)


def test_fixed_closes_at_tp3() -> None:
    result = run("FEST")
    assert (result["exit_reason"], result["exit_price"]) == ("TP3", 130.0)


def test_runner_trails_past_tp3() -> None:
    result = run("LAEUFER")
    assert result["exit_reason"] == "RUNNER_STOP"
    assert result["exit_price"] > 130.0
    assert result["best_price"] >= 150.0


def test_wide_runner_never_trails_on_unfinished_hours() -> None:
    result = run("LAEUFER_WEIT")
    assert result["exit_reason"] in {"RUNNER_STOP", "STOP", "OFFEN"}


def test_orderflow_runner_follows_delta() -> None:
    bars = range(int(T0.timestamp()), int(T0.timestamp()) + 20 * 900, 900)
    assert run("OF_LAEUFER", {b: 50.0 for b in bars})["exit_price"] == run("LAEUFER")["exit_price"]
    assert run("OF_LAEUFER", {b: -50.0 for b in bars})["exit_reason"] == "TP3"
    assert run("OF_LAEUFER", {})["exit_reason"] == "TP3"  # no data: the journal's target


def test_orderflow_ignores_running_bar() -> None:
    entry = {"direction": "LONG", "filled_at": ev._iso(T0)}
    moment = T0 + timedelta(minutes=50)  # inside the 4th 15m bar (open 00:45)
    base = int(T0.timestamp())
    deltas = {base: 1.0, base + 900: 1.0, base + 1800: 1.0, base + 2700: -1000.0}
    assert ev.orderflow_agrees(entry, deltas, 900, moment) is True
    deltas.pop(base)
    assert ev.orderflow_agrees(entry, deltas, 900, moment) is None


def test_short_mirrors() -> None:
    candles = candles_for([200 - p for p in PATH])
    entry = {**long_entry(candles_for(PATH)), "direction": "SHORT", "entry": 100.0, "stop": 110.0,
             "targets": [85.0, 80.0, 70.0]}
    plan, higher = ev.aggregate(candles, "15m"), ev.aggregate(candles, "1h")
    # mirrored path around 100: 200 - p
    entry.update(entry=100.0, stop=110.0)
    fixed = ev.follow_rest(entry, candles, plan, higher, "FEST")
    runner = ev.follow_rest(entry, candles, plan, higher, "LAEUFER")
    assert (fixed["exit_reason"], fixed["exit_price"]) == ("TP3", 70.0)
    assert runner["exit_reason"] == "RUNNER_STOP" and runner["exit_price"] < 70.0


def test_costs_kraken_and_protocol() -> None:
    entry = {"direction": "LONG", "entry": 100.0, "stop": 90.0, "fill_price": 100.0}
    gross, net = ev.net_r(entry, [(1.0, 110.0, "TP")], ev.KRAKEN)
    assert gross == pytest.approx(1.0)
    assert net == pytest.approx(1.0 - (0.0005 * 100 + 0.0005 * 110) / 10, abs=1e-4)
    _, net_protocol = ev.net_r(entry, [(1.0, 90.0, "STOP")], ev.PROTOCOL)
    assert net_protocol == pytest.approx(-1.0 - (0.0008 * 100 + 0.001 * 90) / 10, abs=1e-4)


def test_entries_without_tp2_keep_the_journal_path() -> None:
    candles = candles_for(PATH)
    entry = {**long_entry(candles), "tp_hits": [], "exit_reason": "STOP", "exit_price": 90.0}
    row = ev.evaluate_entry(entry, candles, ev.aggregate(candles, "15m"), ev.aggregate(candles, "1h"))
    assert {v["net_r"] for v in row["variants"].values()} == {row["variants"]["FEST"]["net_r"]}
    assert row["variants"]["FEST"]["gross_r"] == pytest.approx(-1.0)
    assert ev.evaluate_entry({**entry, "filled_at": None}, candles, [], []) is None


def test_aggregate_skips_incomplete_buckets() -> None:
    candles = minutes_through([100, 101, 102])
    del candles[20]
    bars = ev.aggregate(candles, "15m")
    assert [b["open_time"] for b in bars] == [T0]


def test_summary_and_script(tmp_path) -> None:
    from scripts import research_lab_exit_variants as script

    candles = candles_for(PATH + [112, 106, 100, 96, 95, 94])  # down through every stop
    rows = [{"open_time": int(c["open_time"].timestamp() * 1000), **{k: c[k] for k in ("open", "high", "low", "close")}} for c in candles]
    (tmp_path / "c.json").write_text(json.dumps(rows))
    (tmp_path / "j.json").write_text(json.dumps({"entries": [{**long_entry(candles), "net_r": 1.6}]}))
    assert script.main(["--journal", str(tmp_path / "j.json"), "--candles", str(tmp_path / "c.json"), "--out", str(tmp_path / "out")]) == 0
    report = json.loads((tmp_path / "out" / "ausstieg_varianten.json").read_text())
    summary = report["journals"]["j"]["summary"]
    assert summary["trades"] == 1 and summary["reached_tp2"] == 1
    assert summary["LAEUFER"]["sum_r"] > summary["FEST"]["sum_r"]
    assert "Ausstiegs-Varianten" in (tmp_path / "out" / "ausstieg_varianten.md").read_text()
