"""Volume bubbles on the TIM chart: large market orders from TIM's own aggTrades (display only)."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

from src.dashboard.app import DashboardState
from src.dashboard.chart_live import DEFAULT_GROUPS, GROUP_NAMES, KlineCache, build_live_chart
from src.dashboard.footprint_data import BUBBLE_MIN_USD, BUBBLES_PER_DAY, MAX_BUBBLES_VIEW, refresh, volume_bubbles
from src.dashboard.public_en import GROUPS_EN, english_chart_model

NOW = datetime(2026, 10, 26, 21, 10, tzinfo=timezone.utc)
DAY = datetime(2026, 10, 26, tzinfo=timezone.utc)


class BubbleRepository:
    """Footprint rows are empty; every day has one buy and one sell order, the sell 2 minutes later."""

    def __init__(self):
        self.bubble_calls = []

    async def agg_trade_levels(self, symbol, start, end, tick, bucket_seconds):
        return []

    async def agg_trade_bubbles(self, symbol, start, end, min_usd, limit):
        self.bubble_calls.append((start, end, min_usd, limit))
        moment = start + timedelta(hours=1, milliseconds=250)
        return [{"time": moment + timedelta(minutes=2), "buy": False, "quantity": 3.0, "price": 113_010.0, "usd": 339_030.0, "trades": 4},
                {"time": moment, "buy": True, "quantity": 1.5, "price": 113_000.0, "usd": 169_500.0, "trades": 2}]


def test_refresh_stores_large_orders_per_day_sorted_by_time() -> None:
    state, repo = DashboardState(), BubbleRepository()
    asyncio.run(refresh(repo, state, "BTCUSDT", NOW, days=1))
    assert [call[2:] for call in repo.bubble_calls] == [(BUBBLE_MIN_USD, BUBBLES_PER_DAY)] * 2
    day = state.footprint["bubbles"]["2026-10-26"]
    first = int((DAY + timedelta(hours=1)).timestamp() * 1000) + 250
    assert day == [[first, 113_000.0, 1.5, 1], [first + 120_000, 113_010.0, 3.0, -1]]
    # A finished day is not read again within the hour; a store from before the bubbles existed is filled once.
    repo.bubble_calls.clear()
    asyncio.run(refresh(repo, state, "BTCUSDT", NOW + timedelta(minutes=2), days=1))
    assert [call[0] for call in repo.bubble_calls] == [DAY]
    del state.footprint["bubbles"]["2026-10-25"]
    repo.bubble_calls.clear()
    asyncio.run(refresh(repo, state, "BTCUSDT", NOW + timedelta(minutes=4), days=1))
    assert sorted(call[0] for call in repo.bubble_calls) == [DAY - timedelta(days=1), DAY]


def _store(rows: list[list[float]]) -> dict:
    return {"symbol": "BTCUSDT", "tick": 5.0, "bucket_seconds": 300, "days": {"2026-10-26": []},
            "bubbles": {"2026-10-26": rows}, "bubble_min_usd": BUBBLE_MIN_USD}


def test_view_keeps_window_aligns_to_candles_and_caps_the_count() -> None:
    start = int(DAY.timestamp())
    times = [start + 300 * i for i in range(4)]
    rows = [[(start - 10) * 1000, 100_000.0, 5.0, 1],  # before the window
            [(start + 420) * 1000 + 500, 100_010.0, 2.0, -1],  # inside the second candle
            [(start + 1199) * 1000, 100_020.0, 1.0, 1],  # last candle, still inside
            [(start + 1200) * 1000, 100_030.0, 9.0, 1]]  # after the last candle closed
    view = volume_bubbles(_store(rows), times, 300)
    assert [(i["bar"], i["side"], i["quantity"]) for i in view["items"]] == [(start + 300, -1, 2.0), (start + 900, 1, 1.0)]
    assert view["items"][0]["time"] == start + 420.5 and view["items"][0]["usd"] == 200_020.0
    assert view["max_usd"] == 200_020.0 and view["min_usd"] == 100_020.0 and view["floor_usd"] == BUBBLE_MIN_USD

    many = [[(start + i) * 1000, 100_000.0, 1.0 + i / 1000, 1] for i in range(MAX_BUBBLES_VIEW + 50)]
    capped = volume_bubbles(_store(many), times, 300)["items"]
    assert len(capped) == MAX_BUBBLES_VIEW
    assert min(i["quantity"] for i in capped) == pytest.approx(1.05)  # the smallest 50 dropped
    assert [i["time"] for i in capped] == sorted(i["time"] for i in capped)
    assert volume_bubbles(_store([]), times, 300)["items"] == []
    assert "Keine großen" in volume_bubbles(_store(rows[:1]), times, 300)["note"]
    assert volume_bubbles(None, times, 300)["items"] == []


def test_live_chart_shows_bubbles_for_btc_intraday_only() -> None:
    from tests.test_chart_live import fake_fetch

    fetch = fake_fetch()
    candles = fetch("BTCUSDT", "5m", 1000)
    moment = datetime.fromisoformat(candles[-3]["open_time"]) + timedelta(seconds=90)
    day = moment.date().isoformat()
    store = _store([[int(moment.timestamp() * 1000), float(candles[-3]["close"]), 4.2, -1]])
    store["days"] = {day: [[int(moment.timestamp()) // 300 * 300, 100.0, 1.0, 1.0]]}
    store["bubbles"] = {day: store["bubbles"]["2026-10-26"]}
    now = datetime.fromisoformat(candles[-1]["open_time"]) + timedelta(minutes=1)
    btc = build_live_chart("BTCUSDT", "5m", cache=KlineCache(fetch), now=now, footprint=store)
    assert [i["quantity"] for i in btc["bubbles"]["items"]] == [4.2]
    assert "bubbles" in DEFAULT_GROUPS and "bubbles" in GROUP_NAMES and "bubbles" in GROUPS_EN
    assert english_chart_model(btc)["groups"]["bubbles"].startswith("Volume bubbles")
    eth = build_live_chart("ETHUSDT", "5m", cache=KlineCache(fetch), now=now, footprint=store)
    assert eth["bubbles"]["items"] == []
    daily = build_live_chart("BTCUSDT", "1d", cache=KlineCache(fetch), now=now, footprint=store)
    assert daily["bubbles"]["items"] == []


class _Connection:
    def __init__(self, captured):
        self.captured = captured

    async def fetch(self, query, *args):
        self.captured["query"], self.captured["args"] = query, args
        return [{"trade_time": DAY, "buy": True, "quantity": 2.0, "price": 100_000.0, "usd": 200_000.0, "trades": 3}]


def test_repository_query_groups_one_taker_order_and_only_reads() -> None:
    from src.database.repository import MarketRepository

    captured: dict = {}

    class Acquire:
        async def __aenter__(self):
            return _Connection(captured)

        async def __aexit__(self, *exc):
            return False

    class Database:
        def acquire(self):
            return Acquire()

    repo = MarketRepository(Database())
    rows = asyncio.run(repo.agg_trade_bubbles("BTCUSDT", DAY, NOW, 100_000, 50))
    assert rows == [{"time": DAY, "buy": True, "quantity": 2.0, "price": 100_000.0, "usd": 200_000.0, "trades": 3}]
    query = captured["query"]
    assert "GROUP BY trade_time,buyer_is_maker" in query and "HAVING sum(price*quantity)>=$4" in query and "LIMIT $5" in query
    assert query.lstrip().startswith("SELECT") and not any(word in query for word in ("INSERT", "UPDATE", "DELETE"))
    assert captured["args"] == ("BTCUSDT", DAY, NOW, 100_000.0, 50)
    with pytest.raises(ValueError):
        asyncio.run(repo.agg_trade_bubbles("BTCUSDT", NOW, DAY, 100_000, 50))
    with pytest.raises(ValueError):
        asyncio.run(repo.agg_trade_bubbles("BTCUSDT", DAY, NOW, 0, 50))


def test_repository_query_on_postgres_sums_a_sweep_and_skips_small_orders() -> None:
    """Against the isolated test database (TIM_DURABLE_TEST_DATABASE_URL); skipped without it."""
    database_url = os.getenv("TIM_DURABLE_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("isolated durable-ingestion PostgreSQL URL not provided")
    from src.database.connection import Database
    from src.database.repository import MarketRepository
    from src.models.market_data import Trade

    symbol = "BUBTEST"
    base = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=30)

    async def run():
        database = Database(database_url)
        await database.connect()
        await database.initialize_schema()
        try:
            async with database.acquire() as connection:
                await connection.execute("DELETE FROM agg_trades WHERE symbol=$1", symbol)
            repo = MarketRepository(database)
            sweep = base + timedelta(seconds=5, milliseconds=123)
            trades = [Trade(symbol, 100_000.0, 1.0, sweep, 1, False), Trade(symbol, 100_010.0, 1.0, sweep, 2, False),  # one buy order, two prices
                      Trade(symbol, 99_990.0, 0.5, sweep, 3, True),  # a seller in the same ms: separate, below the floor
                      Trade(symbol, 99_000.0, 3.0, base + timedelta(seconds=9), 4, True),  # one large sell
                      Trade(symbol, 99_500.0, 0.2, base + timedelta(seconds=12), 5, False)]  # small
            for trade in trades:
                assert await repo.insert_agg_trade(trade)
            rows = await repo.agg_trade_bubbles(symbol, base, base + timedelta(minutes=1), 100_000, 10)
            async with database.acquire() as connection:
                await connection.execute("DELETE FROM agg_trades WHERE symbol=$1", symbol)
            return rows
        finally:
            await database.close()

    rows = asyncio.run(run())
    assert [(r["buy"], r["quantity"], r["trades"]) for r in rows] == [(False, 3.0, 1), (True, 2.0, 2)]  # largest first
    assert rows[1]["price"] == pytest.approx(100_005.0) and rows[1]["usd"] == pytest.approx(200_010.0)


def test_browser_draws_bubbles_and_hides_them_with_the_layer(tmp_path, monkeypatch) -> None:
    import json
    import shutil
    import subprocess
    from pathlib import Path

    from src.dashboard import chart_live
    from src.dashboard.public_server import PublicDashboardServer
    from tests.test_chart_live import fake_fetch

    if not shutil.which("node") or subprocess.run(["node", "-e", "require('playwright')"], capture_output=True, timeout=30, check=False).returncode:
        pytest.skip("node with playwright not installed (cloud sandbox has it, the Mac runner not)")
    fetch = fake_fetch()
    monkeypatch.setattr(chart_live, "CACHE", KlineCache(fetch))
    rows, days = [], {}
    for index, candle in enumerate(fetch("BTCUSDT", "5m", 1000)[-160:]):
        if index % 3:
            continue
        opened = datetime.fromisoformat(candle["open_time"])
        moment = opened + timedelta(seconds=40 + index % 200)
        price = candle["low"] + (candle["high"] - candle["low"]) * ((index % 7) / 6)
        rows.append([int(moment.timestamp() * 1000), round(price, 2), round(1.2 + (index % 11) * 1.3, 2), 1 if index % 2 else -1])
        days.setdefault(opened.date().isoformat(), [])
    store = _store([])
    store["days"] = {key: [] for key in days}
    store["bubbles"] = {key: [r for r in rows if datetime.fromtimestamp(r[0] / 1000, timezone.utc).date().isoformat() == key] for key in days}
    state = DashboardState()
    state.footprint = store
    state.plan_journal_path = state.plan_journal_struct_path = state.plan_journal_level_path = tmp_path / "none.json"
    server = PublicDashboardServer(state, "127.0.0.1", 0)
    server.start()
    try:
        script = Path(__file__).resolve().parent.parent / "scripts" / "chart_bubbles_check.mjs"
        result = subprocess.run(["node", str(script), f"http://127.0.0.1:{server.httpd.server_address[1]}", str(tmp_path)],
                                capture_output=True, text=True, timeout=180, check=False)
    finally:
        server.stop()
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report["errors"] == []
    assert report["bubblePixels"] > 200 and report["bubblePixelsHidden"] == 0
    assert report["checked"] == ["bubbles"]
    assert (tmp_path / "bubbles-5m.png").stat().st_size > 10_000
