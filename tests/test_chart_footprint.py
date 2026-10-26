"""Footprint and volume profile for the chart from aggregated aggTrades (display only)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.dashboard import footprint_data
from src.dashboard.app import DashboardState
from src.dashboard.chart_live import KlineCache, build_live_chart
from src.dashboard.footprint_data import BUCKET_SECONDS, footprint_bars, refresh, tick_for, volume_profiles

NOW = datetime(2026, 10, 26, 21, 10, tzinfo=timezone.utc)
DAY = datetime(2026, 10, 26, tzinfo=timezone.utc)


class FakeRepository:
    """Returns one aggregated row per 5-minute bucket and price level; records every call."""

    def __init__(self, levels=(100.0, 105.0, 110.0)):
        self.calls = []
        self.levels = levels

    async def agg_trade_levels(self, symbol, start, end, tick, bucket_seconds):
        self.calls.append((symbol, start, end, tick, bucket_seconds))
        rows = []
        moment = start
        while moment < end:
            for index, level in enumerate(self.levels):
                rows.append({"bucket": moment, "level": level, "bid": 1.0 + index, "ask": 2.0 if index != 1 else 9.0, "trades": 3})
            moment += timedelta(seconds=bucket_seconds)
        return rows


def test_refresh_reads_today_every_time_and_finished_days_once() -> None:
    state, repo = DashboardState(), FakeRepository()
    fetched = asyncio.run(refresh(repo, state, "BTCUSDT", NOW, days=2))
    assert sorted(fetched) == ["2026-10-24", "2026-10-25", "2026-10-26"]
    assert all(call[3] == tick_for("BTCUSDT") and call[4] == BUCKET_SECONDS for call in repo.calls)
    today_call = next(call for call in repo.calls if call[1] == DAY)
    assert today_call[2] == NOW  # the running day ends now, not at midnight
    store = state.footprint
    assert store["symbol"] == "BTCUSDT" and store["source"] and sorted(store["days"]) == sorted(fetched)
    assert store["days"]["2026-10-25"][0] == [int(datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp()), 100.0, 1.0, 2.0]

    repo.calls.clear()
    again = asyncio.run(refresh(repo, state, "BTCUSDT", NOW + timedelta(minutes=2), days=2))
    assert list(again) == ["2026-10-26"] and len(repo.calls) == 1  # only today again
    # A new day rolls the window: the oldest day drops out, the new one is read.
    later = asyncio.run(refresh(repo, state, "BTCUSDT", NOW + timedelta(days=1), days=2))
    assert sorted(later) == ["2026-10-26", "2026-10-27"]  # yesterday was read while running, so it is read once more, complete now
    assert sorted(state.footprint["days"]) == ["2026-10-25", "2026-10-26", "2026-10-27"] and sorted(state.footprint["complete"]) == ["2026-10-25", "2026-10-26"]
    # 25.10. was completed a day ago: one finished day per pass is aggregated again (late inserts), plus today.
    repo.calls.clear()
    asyncio.run(refresh(repo, state, "BTCUSDT", NOW + timedelta(days=1, minutes=5), days=2))
    assert [call[1].date().isoformat() for call in repo.calls] == ["2026-10-25", "2026-10-27"]
    repo.calls.clear()
    asyncio.run(refresh(repo, state, "BTCUSDT", NOW + timedelta(days=1, minutes=7), days=2))
    assert [call[1].date().isoformat() for call in repo.calls] == ["2026-10-27"]  # both finished days are fresh now
    repo.calls.clear()
    asyncio.run(refresh(repo, state, "BTCUSDT", NOW + timedelta(days=1, hours=1, minutes=1), days=2))
    assert [call[1].date().isoformat() for call in repo.calls] == ["2026-10-26", "2026-10-27"]  # 26.10. is an hour old


def test_refresh_keeps_finished_days_when_a_query_fails() -> None:
    state, repo = DashboardState(), FakeRepository()
    asyncio.run(refresh(repo, state, "BTCUSDT", NOW, days=1))
    before = state.footprint

    class Failing(FakeRepository):
        async def agg_trade_levels(self, *args):
            raise RuntimeError("connection lost")

    with pytest.raises(RuntimeError):
        asyncio.run(refresh(Failing(), state, "BTCUSDT", NOW + timedelta(minutes=2), days=1))
    assert state.footprint["days"] == before["days"] and state.footprint["updated_at"] == before["updated_at"]


def test_value_area_crosses_empty_rows() -> None:
    from src.dashboard.footprint_data import _value_area

    assert _value_area({0: 30.0, 5: 50.0, 9: 30.0}, 5) == (5, 9)  # grows across the empty rows 6-8 instead of stopping at the POC
    assert _value_area({0: 10.0, 1: 80.0, 2: 10.0}, 1) == (1, 1)


def test_refresh_for_another_symbol_starts_a_fresh_store() -> None:
    state, repo = DashboardState(), FakeRepository()
    asyncio.run(refresh(repo, state, "BTCUSDT", NOW, days=1))
    asyncio.run(refresh(repo, state, "ETHUSDT", NOW, days=1))
    assert state.footprint["symbol"] == "ETHUSDT" and state.footprint["tick"] == tick_for("ETHUSDT")


def test_volume_profile_has_poc_value_area_and_delta() -> None:
    state = DashboardState()
    asyncio.run(refresh(FakeRepository(), state, "BTCUSDT", NOW, days=1))
    profiles = volume_profiles(state.footprint, NOW)
    assert [p["day"] for p in profiles] == ["2026-10-25", "2026-10-26"]
    today = profiles[-1]
    assert today["running"] and not profiles[0]["running"] and today["label"] == "26.10."
    assert today["poc"] == 105.0  # the level with bid 2 + ask 9 per bucket
    assert today["val"] <= today["poc"] <= today["vah"]
    row = next(r for r in today["rows"] if r["price"] == 105.0)
    assert row["delta"] == pytest.approx(row["ask"] - row["bid"]) and row["delta"] > 0
    assert today["total"] == pytest.approx(sum(r["volume"] for r in today["rows"]))
    assert today["step"] % state.footprint["tick"] == 0


def test_footprint_bars_sum_buckets_and_mark_imbalances() -> None:
    state = DashboardState()
    asyncio.run(refresh(FakeRepository(), state, "BTCUSDT", NOW, days=1))
    times = [int((DAY + timedelta(minutes=30 * i)).timestamp()) for i in range(40)]
    result = footprint_bars(state.footprint, times, 1800)
    assert result["note"] is None and result["step"] >= state.footprint["tick"]
    bars = result["bars"]
    assert bars and bars[0]["time"] == times[0] and all(b["time"] in times for b in bars)
    first = bars[0]
    by_price = {level[0]: level for level in first["levels"]}
    assert by_price[105.0][1] == pytest.approx(6 * 2.0) and by_price[105.0][2] == pytest.approx(6 * 9.0)  # six 5-minute buckets
    assert first["delta"] == pytest.approx(sum(l[2] - l[1] for l in first["levels"]))
    assert first["poc"] == 105.0
    assert [105.0, "ask"] in first["imbalances"]  # ask 54 against bid 6 one level below
    # Views finer than the stored bucket get no footprint, only a note.
    assert footprint_bars(state.footprint, times, 60)["note"].startswith("Footprint ab 5m")
    assert footprint_bars({}, times, 1800)["note"]


def test_live_chart_carries_trades_only_for_the_collected_symbol() -> None:
    from tests.test_chart_live import fake_fetch

    state = DashboardState()
    asyncio.run(refresh(FakeRepository(levels=(113_000.0, 113_005.0, 113_010.0)), state, "BTCUSDT", NOW, days=1))
    btc = build_live_chart("BTCUSDT", "30m", cache=KlineCache(fake_fetch()), now=NOW, footprint=state.footprint)
    assert btc["volume_profile"] and btc["footprint"]["bars"] and btc["trade_source"] == footprint_data.SOURCE
    assert "vp" in btc["default_groups"] and "fp" in btc["groups"]
    eth = build_live_chart("ETHUSDT", "30m", cache=KlineCache(fake_fetch()), now=NOW, footprint=state.footprint)
    assert eth["volume_profile"] == [] and eth["footprint"]["bars"] == [] and "nur für BTCUSDT" in eth["footprint"]["note"]
    none = build_live_chart("BTCUSDT", "30m", cache=KlineCache(fake_fetch()), now=NOW, footprint={})
    assert "Noch keine Trades" in none["footprint"]["note"]
    daily = build_live_chart("BTCUSDT", "1d", cache=KlineCache(fake_fetch()), now=NOW, footprint=state.footprint)
    assert daily["volume_profile"] == [] and daily["footprint"]["bars"] == []


def test_repository_query_aggregates_per_bucket_level_and_side() -> None:
    from src.database.repository import MarketRepository

    captured = {}

    class Connection:
        async def fetch(self, query, *args):
            captured["query"], captured["args"] = query, args
            return [{"bucket": DAY, "level": 113_000.0, "bid": 1.5, "ask": 0.0, "trades": 2}]

    class Acquire:
        async def __aenter__(self):
            return Connection()

        async def __aexit__(self, *exc):
            return False

    class Database:
        def acquire(self):
            return Acquire()

    repo = MarketRepository(Database())
    rows = asyncio.run(repo.agg_trade_levels("BTCUSDT", DAY, NOW, 5.0, 300))
    assert rows == [{"bucket": DAY, "level": 113_000.0, "bid": 1.5, "ask": 0.0, "trades": 2}]
    query = captured["query"]
    assert "FILTER (WHERE buyer_is_maker)" in query and "FILTER (WHERE NOT buyer_is_maker)" in query and "GROUP BY 1,2" in query
    assert query.lstrip().startswith("SELECT") and "INSERT" not in query and "UPDATE" not in query and "DELETE" not in query
    assert captured["args"] == ("BTCUSDT", DAY, NOW, 300.0, 5.0)
    with pytest.raises(ValueError):
        asyncio.run(repo.agg_trade_levels("BTCUSDT", NOW, DAY, 5.0, 300))
    with pytest.raises(ValueError):
        asyncio.run(repo.agg_trade_levels("BTCUSDT", DAY, NOW, 0, 300))
