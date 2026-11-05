"""GARCH-4h paper sizing (S15-4h frozen parameters) and its use in the plan journal."""

from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dashboard import plan_journal as pj
from src.research_lab import vol_4h

START = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _candles(returns: list[float], price: float = 100_000.0) -> list[dict]:
    out = []
    for k, r in enumerate(returns):
        opened = START + timedelta(hours=4 * k)
        close = price * math.exp(r / 100)
        out.append({"timeframe": "4h", "open_time": opened, "close_time": opened + timedelta(hours=4) - timedelta(milliseconds=1),
                    "open": price, "high": max(price, close), "low": min(price, close), "close": close})
        price = close
    return out


def test_forecast_is_the_frozen_garch_recursion():
    rets = [random.Random(1).gauss(0, 1) for _ in range(120)]
    omega, alpha, beta = vol_4h.PARAMS["BTCUSDT"]
    h = sum(r * r for r in rets[:84]) / 84
    for r in rets:
        h = omega + alpha * r * r + beta * h
    assert vol_4h.forecast_variance(rets, "BTC-USDT") == pytest.approx(h)
    assert vol_4h.forecast_variance(rets[:83], "BTCUSDT") is None  # warm-up not complete
    assert vol_4h.forecast_variance(rets, "DOGEUSDT") is None  # no frozen parameters


def test_only_candles_closed_before_the_moment_count():
    rets = [0.5] * 100
    candles = _candles(rets)
    at = candles[89]["close_time"] + timedelta(milliseconds=1)
    assert len(vol_4h.returns_4h(candles, at)) == 90
    changed = candles[:90] + [{**c, "close": c["open"] * 1.09} for c in candles[90:]]  # wild future must not matter
    assert vol_4h.returns_4h(changed, at) == vol_4h.returns_4h(candles, at)
    assert vol_4h.returns_4h([{**candles[0], "closed": False}], at) == []


def test_sizing_fields_and_weight_clip():
    calm = _candles([0.2 if k % 2 else -0.2 for k in range(100)])
    at = calm[-1]["close_time"]
    plan = {"symbol": "BTCUSDT", "entry": 100_000.0, "stop": 99_000.0}
    f = vol_4h.sizing(plan, calm, at)
    sigma = math.sqrt(vol_4h.forecast_variance(vol_4h.returns_4h(calm, at), "BTCUSDT"))
    assert f["sigma_pct"] == pytest.approx(sigma, abs=1e-4)
    assert f["weight"] == vol_4h.W_MAX  # far calmer than the 2023-2024 median: capped at 2
    assert f["stop_sigma"] == pytest.approx(1.0 / sigma, abs=1e-3)
    assert f["garch_1r"] == pytest.approx(sigma / 100 * 100_000, abs=0.01)
    assert f["size"] == pytest.approx(f["risk_usd"] / 1000.0)
    wild = _candles([4.0 if k % 2 else -4.0 for k in range(100)])
    assert vol_4h.sizing(plan, wild, wild[-1]["close_time"])["weight"] == vol_4h.W_MIN
    assert vol_4h.sizing({**plan, "stop": 100_000.0}, calm, at) is None
    assert vol_4h.sizing(plan, calm[:50], at) is None
    assert vol_4h.sizing(plan, calm, at + timedelta(hours=4)) is None  # newest 4h candle missing: no stale forecast
    assert f["based_on"] == (calm[-1]["close_time"] + timedelta(milliseconds=1)).isoformat()


def test_weighted_sum_uses_only_entries_with_a_weight():
    rows = [{"net_r": 1.0, "vol_4h": {"weight": 2.0}}, {"net_r": -1.0, "vol_4h": {"weight": 0.5}}, {"net_r": 3.0}]
    w = vol_4h.weighted(rows)
    assert w == {"closed": 2, "sum_net_r": 0.0, "sum_vol_net_r": 1.5, "sum_vol_net_r_norm": 1.2, "mean_weight": 1.25}
    assert vol_4h.weighted([])["mean_weight"] is None
    assert vol_4h.weighted([])["sum_vol_net_r_norm"] == 0.0


@pytest.mark.parametrize("weight", [0.5, 1.0, 1.5, 2.0])
def test_constant_weights_normalise_to_the_plain_sum(weight):
    # Issue #100: the level of the weights alone must not make a journal look better or worse.
    rows = [{"net_r": r, "vol_4h": {"weight": weight}} for r in (1.2, -0.8, 2.5, -1.0, 0.3)]
    w = vol_4h.weighted(rows)
    assert w["sum_vol_net_r"] == pytest.approx(weight * w["sum_net_r"], abs=1e-3)
    assert w["sum_vol_net_r_norm"] == w["sum_net_r"] == 2.2


def test_normalised_sum_shows_only_redistribution():
    # Same mean weight 1.0: more size on the winner, less on the loser -> better than plain.
    rows = [{"net_r": 2.0, "vol_4h": {"weight": 1.5}}, {"net_r": -1.0, "vol_4h": {"weight": 0.5}}]
    w = vol_4h.weighted(rows)
    assert w["sum_net_r"] == 1.0 and w["mean_weight"] == 1.0
    assert w["sum_vol_net_r_norm"] == 2.5
    # Doubling every weight changes the raw sum but not the normalised one.
    doubled = vol_4h.weighted([{**r, "vol_4h": {"weight": r["vol_4h"]["weight"] * 2}} for r in rows])
    assert doubled["sum_vol_net_r"] == 5.0 and doubled["sum_vol_net_r_norm"] == 2.5


def test_plan_journal_records_vol_fields_and_summary(tmp_path: Path):
    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series: dict[str, list[dict]] = {"30m": [], "1m": []}
    price = 100_000.0
    for i in range(90):
        opened = start + timedelta(minutes=30 * i)
        close = price + (400 if (i // 10) % 2 else -400)
        series["30m"].append({"timeframe": "30m", "open_time": opened.isoformat(), "close_time": (opened + timedelta(minutes=29, seconds=59.999)).isoformat(),
                              "open": price, "high": max(price, close) + 50, "low": min(price, close) - 50, "close": close, "volume": 10.0})
        price = close
    now = start + timedelta(minutes=30 * 90)
    rng = random.Random(4)
    four = []
    p = 100_000.0
    for k in range(100):  # 4h history that ends before the first 30m close used
        opened = now - timedelta(hours=4 * (100 - k))
        close = p * math.exp(rng.gauss(0, 1) / 100)
        four.append({"timeframe": "4h", "open_time": opened.isoformat(), "close_time": (opened + timedelta(hours=3, minutes=59, seconds=59.999)).isoformat(),
                     "open": p, "high": max(p, close), "low": min(p, close), "close": close, "volume": 1.0})
        p = close
    with_four = {**series, "4h": four}
    journal = pj.update(tmp_path / "j.json", with_four, now)
    assert journal["entries"]
    for entry in journal["entries"]:
        v = entry["vol_4h"]
        assert v["model"] == vol_4h.MODEL and vol_4h.W_MIN <= v["weight"] <= vol_4h.W_MAX and v["periods"] >= vol_4h.WARMUP
    plain = pj.update(tmp_path / "p.json", series, now)
    assert all("vol_4h" not in e for e in plain["entries"])  # no 4h history: field left out, plan unchanged
    strip = lambda e: {k: v for k, v in e.items() if k != "vol_4h"}
    assert [strip(e) for e in journal["entries"]] == [strip(e) for e in plain["entries"]]
    assert pj.summary(journal)["vol_sizing"]["closed"] == 0
    again = pj.update(tmp_path / "j.json", with_four, now + timedelta(minutes=1))
    assert again["log_seq"] == journal["log_seq"]  # restart with the same candles: no new events
    assert pj.rebuild(tmp_path / "j.json")["entries"] == again["entries"]


def test_old_entries_without_the_field_still_render():
    from src.dashboard.pages.plan_journal import _plan_journal_page
    old = {"entries": [{"id": "a", "direction": "LONG", "status": "CLOSED", "gross_r": 1.0, "net_r": 0.9, "timeframe": "30m"}]}
    stats = pj.summary(old)
    assert stats["vol_sizing"] == {"closed": 0, "sum_net_r": 0.0, "sum_vol_net_r": 0.0, "sum_vol_net_r_norm": 0.0, "mean_weight": None}
    assert "Netto-R mit GARCH-Größe" in _plan_journal_page({}, old)
