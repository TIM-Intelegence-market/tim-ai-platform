"""Perp-Schatten (Master-Analyse 09.11.2026, P1c/P5): the 15m/1h rule on perp candles with a trade-based profile."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dashboard import perp_journal
from src.dashboard.chart_live import KlineCache
from tests.test_chart_live import fake_fetch
from tests.test_perp_flow import _store

NOW = datetime(2026, 10, 26, 21, 10, tzinfo=timezone.utc)


def _perp_cache(calls: list | None = None) -> KlineCache:
    spot = fake_fetch(calls)

    def perp(symbol: str, interval: str, limit: int) -> list[dict]:  # perp a basis of 35 USDT below spot
        return [{**r, **{k: r[k] - 35.0 for k in ("open", "high", "low", "close")}} for r in spot(symbol, interval, limit)]

    return KlineCache(perp)


def test_perp_series_keeps_closed_candles_only_and_names_timeframes() -> None:
    calls: list = []
    series, errors = perp_journal.perp_series(_perp_cache(calls), "BTCUSDT")
    assert not errors and set(series) == set(perp_journal.SERIES)
    assert {c for c, *_ in calls} == {"BTCUSDT"} and ("BTCUSDT", "1m", 1000) in calls
    for timeframe, rows in series.items():
        assert all(r["timeframe"] == timeframe and r.get("closed", True) for r in rows)
        assert datetime.fromisoformat(rows[-1]["close_time"]) <= NOW


def test_trade_profile_from_perp_rows_or_none() -> None:
    store = _store("perp", -2.0, NOW - timedelta(hours=10), 10)
    candles = [{"open_time": NOW - timedelta(hours=8), "close_time": NOW - timedelta(hours=7, minutes=30)},
               {"open_time": NOW - timedelta(hours=1), "close_time": NOW - timedelta(minutes=30)}]
    profile = perp_journal.trade_profile(store, candles, NOW)
    assert profile and profile["source"].startswith("Perp-Trades") and profile["val"] <= profile["poc"] <= profile["vah"]
    # window starts before the store: no partial profile
    early = [{"open_time": NOW - timedelta(hours=20), "close_time": NOW - timedelta(hours=19)}, candles[-1]]
    assert perp_journal.trade_profile(store, early, NOW) is None
    assert perp_journal.trade_profile(None, candles, NOW) is None
    assert perp_journal.trade_profile({"days": {}}, candles, NOW) is None


def test_update_writes_both_perp_journals_with_their_source(tmp_path: Path) -> None:
    store = {**_store("perp", -2.0, NOW - timedelta(days=6), 24 * 6), "tick": 5.0}
    paths = {"15m": tmp_path / "perp_short.json", "1h": tmp_path / "perp_mid.json"}
    status = perp_journal.update(_perp_cache(), store, NOW, paths)
    assert not status["errors"] and set(status["journals"]) == {"15m", "1h"}
    for timeframe, path in paths.items():
        view = json.loads(path.read_text(encoding="utf-8"))
        assert view["source"] == perp_journal.SOURCE and view["last_plan_candle"]
        assert status["journals"][timeframe]["plans"] == len(view["entries"])
        for entry in view["entries"]:  # perp prices, never spot
            assert entry["entry"] < 200_000
    # a second step with the same candles changes nothing
    again = perp_journal.update(_perp_cache(), store, NOW + timedelta(minutes=1), paths)
    assert again["journals"]["15m"]["plans"] == status["journals"]["15m"]["plans"]


def test_update_without_perp_candles_skips(tmp_path: Path) -> None:
    def offline(symbol: str, interval: str, limit: int) -> list[dict]:
        raise OSError("no route")

    status = perp_journal.update(KlineCache(offline), None, NOW, {"15m": tmp_path / "a.json"})
    assert status["errors"] and status["journals"]["15m"] == {"skipped": "keine Perp-Kerzen"}
    assert not (tmp_path / "a.json").exists()


def test_plan_journal_update_uses_the_external_profile(tmp_path: Path) -> None:
    from src.dashboard import plan_journal as pj
    from tests.test_plan_journal import _series

    start = datetime(2026, 10, 22, 0, 0, tzinfo=timezone.utc)
    series = _series(start)
    seen: list[tuple[int, datetime]] = []

    def profile_fn(candles, at):
        seen.append((len(candles), at))
        return {"poc": 100_000.0, "vah": 100_400.0, "val": 99_600.0, "source": "test"}

    journal = pj.update(tmp_path / "j.json", series, start + timedelta(minutes=30 * 90), profile_fn=profile_fn, source="Testquelle")
    assert seen and seen[0][0] <= pj.PLAN_VISIBLE and journal["source"] == "Testquelle"
    assert json.loads((tmp_path / "j.json").read_text(encoding="utf-8"))["source"] == "Testquelle"
