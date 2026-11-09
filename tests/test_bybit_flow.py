"""Bybit perp trades as the second venue of the chart's bubbles (src/dashboard/bybit_flow.py, Issue #162)."""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src.dashboard import bybit_flow
from src.dashboard.bybit_flow import BybitFlow, run

NOW = datetime(2026, 11, 9, 14, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def _message(rows: list[tuple[int, str, str, str]]) -> str:
    return json.dumps({"topic": "publicTrade.BTCUSDT", "type": "snapshot", "ts": rows[-1][0],
                       "data": [{"T": ms, "s": "BTCUSDT", "S": side, "v": qty, "p": price, "L": "PlusTick", "i": f"id-{ms}-{qty}", "BT": False}
                                for ms, side, price, qty in rows]})


def _flow(tmp_path, clock_ms: int = NOW_MS) -> BybitFlow:
    return BybitFlow(tmp_path, clock=lambda: clock_ms / 1000)


def test_trades_become_rows_and_same_millisecond_orders_become_one_bubble(tmp_path) -> None:
    flow = _flow(tmp_path)
    flow.connected()
    ms = NOW_MS - 600_000
    assert flow.handle_message(_message([(ms, "Buy", "74002.5", "1.0"), (ms, "Buy", "74003", "1.0"), (ms + 5, "Sell", "74000", "0.5"),
                                         (ms + 9, "Sell", "74000", "0.1")])) == 4
    assert flow.handle_message(json.dumps({"op": "pong", "success": True})) == 0 and flow.handle_message("not json") == 0
    flow.disconnected()
    day = NOW.date().isoformat()
    rows = flow.rows(day)
    bucket = ms // 1000 // 300 * 300
    assert rows == [[bucket, 74000.0, 0.6, 2.0]]  # 5 $ level: taker buys into the ask, sells into the bid
    bubbles = flow.bubbles[day]
    assert len(bubbles) == 1 and bubbles[0][2] == 2.0 and bubbles[0][3] == 1 and abs(bubbles[0][1] - 74002.75) < 1e-6  # 148 k$ buy order
    store = flow.store()
    assert store["venue"] == "bybit" and store["market"] == "perp" and store["bubbles"][day] == bubbles
    assert store["health"]["trades"] == 4 and store["health"]["sessions"] == 1 and not store["health"]["connected"]
    assert store["complete"] == {}  # one short stretch does not cover the day


def test_save_load_roundtrip_and_replayed_old_trades_are_ignored(tmp_path) -> None:
    flow = _flow(tmp_path)
    flow.connected()
    ms = NOW_MS - 300_000
    flow.handle_message(_message([(ms, "Buy", "74000", "2.0"), (ms + 1000, "Sell", "74010", "3.0")]))
    flow.disconnected()
    flow.save()
    assert (tmp_path / "state.json").exists() and list(tmp_path.glob("bybit-*.json.gz"))
    again = _flow(tmp_path)
    again.load()
    assert again.rows(NOW.date().isoformat()) == flow.rows(NOW.date().isoformat()) and again.segments == flow.segments
    assert again.bubbles == flow.bubbles and again.trades == 2 and again.last_trade_ms == ms + 1000
    again.connected()
    assert again.handle_message(_message([(ms - 120_000, "Buy", "74000", "1.0")])) == 1  # a replay from before the last trade
    assert again.trades == 2  # not counted again
    again.handle_message(_message([(ms + 30_000, "Buy", "74020", "1.0")]))
    assert len(again.segments) == 2  # 29 s without trades after a reconnect: a new stretch, the hole stays visible


def test_prune_drops_old_days_and_stale_detects_a_dead_socket(tmp_path) -> None:
    flow = _flow(tmp_path)
    flow.connected()
    old = NOW_MS - 20 * 86_400_000
    flow.handle_message(_message([(old, "Buy", "70000", "1.0"), (NOW_MS - 1000, "Sell", "74000", "1.0")]))
    flow.prune()
    assert list(flow.days) == [NOW.date().isoformat()] and len(flow.segments) == 1
    assert not flow.stale()
    flow.clock = lambda: NOW_MS / 1000 + 200
    assert flow.stale()
    flow.disconnected()
    assert not flow.stale()


class FakeSocket:
    def __init__(self, messages: list[str]) -> None:
        self.messages = list(messages)
        self.sent: list[str] = []

    async def send(self, text: str) -> None:
        self.sent.append(text)

    async def recv(self) -> str:
        if not self.messages:
            raise ConnectionError("closed")
        return self.messages.pop(0)


class FakeConnect:
    def __init__(self, sockets: list[FakeSocket]) -> None:
        self.sockets = list(sockets)
        self.urls: list[str] = []

    def __call__(self, url: str):
        self.urls.append(url)
        socket = self.sockets.pop(0)
        connect = self

        class Context:
            async def __aenter__(self):
                return socket

            async def __aexit__(self, *exc):
                return False

        return Context()


def test_run_subscribes_aggregates_publishes_and_reconnects(tmp_path) -> None:
    ms = NOW_MS - 60_000
    first = FakeSocket([json.dumps({"op": "subscribe", "success": True}), _message([(ms, "Buy", "74000", "2.0")])])
    second = FakeSocket([_message([(ms + 2000, "Sell", "74010", "1.5")])])
    connect = FakeConnect([first, second])
    state = SimpleNamespace(lock=threading.Lock(), bybit_flow={})
    stop = asyncio.Event()
    flow = _flow(tmp_path)
    bybit_flow.MAX_BACKOFF_SECONDS, saved = 0.01, bybit_flow.MAX_BACKOFF_SECONDS

    async def scenario():
        task = asyncio.create_task(run(state, stop, tmp_path, connect=connect, flow=flow, save_seconds=0.0))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if len(connect.urls) >= 2 and not connect.sockets and state.bybit_flow.get("health", {}).get("trades") == 2:
                break
        stop.set()
        await asyncio.wait_for(task, timeout=5)

    try:
        asyncio.run(scenario())
    finally:
        bybit_flow.MAX_BACKOFF_SECONDS = saved
    assert connect.urls[:2] == [bybit_flow.WS_URL] * 2
    assert json.loads(first.sent[0]) == {"op": "subscribe", "args": ["publicTrade.BTCUSDT"]}
    assert state.bybit_flow["health"]["trades"] == 2 and state.bybit_flow["health"]["sessions"] == 2
    assert state.bybit_flow["bubbles"][NOW.date().isoformat()][0][2] == 2.0  # the 148 k$ buy is a bubble, the 111 k$ sell too
    assert (tmp_path / "state.json").exists()


def test_live_chart_merges_bybit_bubbles_on_the_perp_only() -> None:
    from src.dashboard.chart_live import KlineCache, build_live_chart
    from src.dashboard.public_en import english_chart_model
    from tests.test_chart_live import NOW as CHART_NOW, fake_fetch

    start = CHART_NOW - timedelta(hours=3)
    day = start.date().isoformat()

    def store(venue: str | None, usd: float) -> dict:
        ms = int((start + timedelta(hours=1)).timestamp() * 1000)
        quantity = usd / 60_000
        base = {"symbol": "BTCUSDT", "market": "perp", "tick": 5.0, "bucket_seconds": 300,
                "days": {day: [[int(start.timestamp()), 60_000.0, 1.0, 1.0]]}, "complete": {},
                "bubbles": {day: [[ms, 60_000.0, quantity, 1]]}, "bubble_min_usd": 100_000.0, "source": "x"}
        return dict(base, venue=venue) if venue else base

    perp, bybit = store(None, 300_000), store("bybit", 200_000)
    model = build_live_chart("BTCUSDT", "1h", cache=KlineCache(fake_fetch()), perp_cache=KlineCache(fake_fetch()), now=CHART_NOW,
                             perp=perp, bybit=bybit, market="perp", liquidation_root=False)
    assert model["bubbles"]["venues"] == ["binance", "bybit"]
    assert sorted((i["venue"], i["usd"]) for i in model["bubbles"]["items"]) == [("binance", 300_000.0), ("bybit", 200_000.0)]
    assert model["bubbles"]["min_usd"] == 200_000.0 and model["bubbles"]["max_usd"] == 300_000.0
    spot = build_live_chart("BTCUSDT", "1h", cache=KlineCache(fake_fetch()), now=CHART_NOW, footprint=dict(perp, market="spot"),
                            perp=perp, bybit=bybit, market="spot", liquidation_root=False)
    assert spot["bubbles"]["venues"] == ["binance"] and all(i["venue"] == "binance" for i in spot["bubbles"]["items"])
    english = english_chart_model(model)
    assert english["groups"]["bubbles"].startswith("Volume bubbles") and "Bybit" in english["groups"]["bubbles"]
