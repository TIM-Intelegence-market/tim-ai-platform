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

    async def agg_trade_bubbles(self, symbol, start, end, min_usd, limit):
        return []  # volume bubbles have their own tests (test_chart_bubbles.py)


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


def _store(rows_by_bucket: dict[int, list[tuple[float, float, float]]], tick: float = 5.0) -> dict:
    """A footprint store with given [level, bid, ask] rows per 5-minute bucket."""
    rows = [[bucket, level, bid, ask] for bucket, levels in sorted(rows_by_bucket.items()) for level, bid, ask in levels]
    return {"symbol": "BTCUSDT", "tick": tick, "bucket_seconds": BUCKET_SECONDS, "source": "test", "updated_at": NOW.isoformat(),
            "days": {"2026-10-26": rows}, "complete": {}}


def test_footprint_bars_mark_stacked_imbalances_and_auction_edges() -> None:
    start = int(DAY.timestamp())
    # Buyers lift the ask three levels in a row against thin bids one level below: a stacked buy imbalance.
    # The high (120) traded on both sides: unfinished auction; the low (100) only on the bid: finished.
    levels = [(100.0, 1.0, 0.0), (105.0, 1.0, 8.0), (110.0, 1.0, 8.0), (115.0, 1.0, 8.0), (120.0, 1.0, 1.0)]
    result = footprint_bars(_store({start: levels, start + 300: levels}), [start, start + 300], 300)
    assert result["step"] == 5.0  # rows small enough to keep the tick
    bar = result["bars"][0]
    assert [[105.0, "ask"], [110.0, "ask"], [115.0, "ask"]] == [i for i in bar["imbalances"] if i[1] == "ask"]
    assert bar["stacked"] == [[105.0, 115.0, "ask"]]
    assert bar["unfinished_high"] is True and bar["unfinished_low"] is False
    # Two imbalances are no stack; a gap in the run breaks it.
    short = footprint_bars(_store({start: levels[:3] + [(115.0, 1.0, 1.0)], start + 300: levels}), [start, start + 300], 300)
    assert short["bars"][0]["stacked"] == []


def test_footprint_imbalance_compares_with_the_row_one_step_away_even_when_empty() -> None:
    start = int(DAY.timestamp())
    # 100 bid 4, 105 nothing traded, 110 ask 3 / bid 1, 115 ask 1: the row below 110 is empty (zero bid),
    # so 110's ask is an imbalance; the populated row two steps down (bid 4) must not be used.
    levels = [(100.0, 4.0, 0.5), (110.0, 1.0, 3.0), (115.0, 0.1, 1.0)]
    result = footprint_bars(_store({start: levels, start + 300: levels}), [start, start + 300], 300)
    assert result["step"] == 5.0
    bar = result["bars"][0]
    assert [110.0, "ask"] in bar["imbalances"]
    # 100's bid against the empty row 105 (zero ask) counts as well; the highest row has nothing above.
    assert [100.0, "bid"] in bar["imbalances"] and [115.0, "bid"] not in bar["imbalances"]


def test_footprint_rows_stay_fine_enough_for_zooming() -> None:
    start = int(DAY.timestamp())
    # A 300 USD range per bar: about 30 rows are sent (the chart merges them when zoomed out).
    levels = [(100_000.0 + 5 * i, 1.0, 1.0) for i in range(60)]
    result = footprint_bars(_store({start: levels, start + 300: levels}), [start, start + 300], 300)
    assert 20 <= len(result["bars"][0]["levels"]) <= 60
    assert result["step"] % 5.0 == 0


def test_browser_shows_footprint_after_the_button(tmp_path, monkeypatch) -> None:
    import shutil
    import subprocess
    import json
    from pathlib import Path

    from src.dashboard import chart_live
    from src.dashboard.public_server import PublicDashboardServer
    from tests.test_chart_live import fake_fetch

    if not shutil.which("node") or subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, timeout=30, check=False).returncode:
        pytest.skip("node with playwright not installed (cloud sandbox has it, the Mac runner not)")
    fetch = fake_fetch()
    monkeypatch.setattr(chart_live, "CACHE", KlineCache(fetch))
    # Trades inside every 5m candle: bid x ask on each 5 USD tick between low and high.
    rows: dict[int, list[tuple[float, float, float]]] = {}
    for candle in fetch("BTCUSDT", "5m", 1000)[-300:]:
        bucket = int(datetime.fromisoformat(candle["open_time"]).timestamp())
        low, high = int(candle["low"] // 5) * 5, int(candle["high"] // 5) * 5
        rows[bucket] = [(float(level), 1.0 + (level // 5) % 3, 2.0 + (level // 5) % 4) for level in range(low, high + 5, 5)]
    store = _store(rows)
    store["days"] = {datetime.fromtimestamp(min(rows), timezone.utc).date().isoformat(): store["days"]["2026-10-26"]}
    state = DashboardState()
    state.footprint = store
    state.plan_journal_path = state.plan_journal_struct_path = state.plan_journal_level_path = tmp_path / "none.json"
    server = PublicDashboardServer(state, "127.0.0.1", 0)
    server.start()
    try:
        script = Path(__file__).resolve().parent.parent / "scripts" / "chart_footprint_check.mjs"
        result = subprocess.run(["node", str(script), f"http://127.0.0.1:{server.httpd.server_address[1]}", str(tmp_path)],
                                capture_output=True, text=True, timeout=180, check=False)
    finally:
        server.stop()
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["errors"] == []
    assert report["yellowZoomedOut"] == 0  # zoomed out: only the hint, no cells
    assert report["yellowFootprint"] > 100  # after the button: POC frames of the bid x ask cells
    assert {"day", "tpo", "vp", "fp"} <= set(report["legacyChecked"]) and "week" not in report["legacyChecked"]
    assert (tmp_path / "footprint-5m.png").stat().st_size > 10_000
