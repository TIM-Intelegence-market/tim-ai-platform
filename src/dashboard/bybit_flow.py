"""Bybit linear perp trades as a second venue for the TIM chart's volume bubbles (display only).

Issue #162 (Master-Analyse 09.11.2026): Broncx's MMT layout shows "Volume Bubbles (2 venues)". TIM's
first venue is Binance USD-M (``perp_flow.py``, REST ``aggTrades`` by id, gapless). Bybit's REST
``recent-trade`` has no id paging and holds only the newest 1 000 trades, so the second venue is
the public websocket ``publicTrade.BTCUSDT`` (``wss://stream.bybit.com/v5/public/linear``), the same
host the S12 liquidation collector already reads. No key, no account, nothing is traded.

Every trade is aggregated at once into the footprint store's rows ``[bucket, level, bid, ask]``
(5-minute buckets, 5 $ levels; ``S = Buy`` is the taker's side, so Buy goes into the ask) and large
taker orders (trades of the same millisecond and side) above ``BUBBLE_MIN_USD`` become bubbles.
Rows and bubbles are saved per UTC day under ``data/bybit_flow/``; a restart resumes from the files.
A websocket has no id to resume from, so the record is complete only while connected: ``segments``
holds the connected stretches and the chart's ``complete`` days are the ones covered by one stretch.

The chart merges these bubbles with the Binance ones when the perp is shown (``venue`` on each
item); footprint, CVD, volume profile and levels stay Binance.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from src.dashboard.perp_flow import BUBBLE_MIN_USD, BUBBLES_PER_DAY, BUCKET_SECONDS, DAYS_KEPT, TICK, _day_key, _day_start_ms

WS_URL = "wss://stream.bybit.com/v5/public/linear"
SYMBOL = "BTCUSDT"
VENUE = "bybit"
TOPIC = f"publicTrade.{SYMBOL}"
DATA_DIR = Path("data/bybit_flow")
SOURCE = "Bybit Linear Perp publicTrade (BTCUSDT, öffentlich, TIM-Sammler)"
SAVE_SECONDS = 60
CLIENT_PING_SECONDS = 20.0  # Bybit expects {"op": "ping"} about every 20 s
MAX_BACKOFF_SECONDS = 60.0
MAX_MESSAGE_BYTES = 1 << 20
STALE_SECONDS = 180  # no trade for 3 minutes on a BTC perp: the socket is dead, reconnect
SEGMENT_GAP_MS = 10_000  # a quiet stretch longer than this after a reconnect counts as a hole

Connect = Callable[[str], Any]


def _default_connect(url: str) -> Any:
    from websockets.asyncio.client import connect

    return connect(url, ping_interval=20, ping_timeout=20, open_timeout=15, close_timeout=5, max_size=MAX_MESSAGE_BYTES)


class BybitFlow:
    """Aggregated Bybit trade record for one symbol. Not thread-safe: one runner calls it."""

    def __init__(self, directory: Path | str = DATA_DIR, clock: Callable[[], float] | None = None, symbol: str = SYMBOL) -> None:
        self.directory = Path(directory)
        self.clock = clock or time.time
        self.symbol = symbol
        self.tick = TICK
        self.days: dict[str, dict[tuple[int, float], list[float]]] = {}
        self.bubbles: dict[str, list[list[float]]] = {}
        self.segments: list[list[int]] = []  # [first_ms, last_ms] of each connected stretch
        self.sessions = 0
        self.messages = 0
        self.trades = 0
        self.updated_at: str | None = None
        self.last_trade_ms: int | None = None
        self._dirty: set[str] = set()
        self._order: list[float] | None = None  # running taker order [ms, side, quantity, notional]
        self._connected = False

    # --- persistence -------------------------------------------------------------------------

    def load(self) -> None:
        state_file = self.directory / "state.json"
        if state_file.exists():
            state = json.loads(state_file.read_text())
            if state.get("symbol") == self.symbol:
                self.segments = [list(map(int, s)) for s in state.get("segments") or []]
                self.sessions = int(state.get("sessions") or 0)
                self.trades = int(state.get("trades") or 0)
                self.updated_at = state.get("updated_at")
                self.last_trade_ms = state.get("last_trade_ms")
        for path in sorted(self.directory.glob("bybit-*.json.gz")):
            try:
                payload = json.loads(gzip.decompress(path.read_bytes()))
            except (OSError, ValueError):
                continue
            key = payload["day"]
            self.days[key] = {(int(b), float(lv)): [float(bid), float(ask)] for b, lv, bid, ask in payload["rows"]}
            self.bubbles[key] = [list(map(float, row)) for row in payload.get("bubbles") or []]

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for key in sorted(self._dirty):
            if key not in self.days:
                continue
            payload = {"day": key, "symbol": self.symbol, "venue": VENUE, "tick": self.tick, "bucket_seconds": BUCKET_SECONDS,
                       "rows": self.rows(key), "bubbles": self.bubbles.get(key, [])}
            self._write(self.directory / f"bybit-{key}.json.gz", gzip.compress(json.dumps(payload).encode()))
        self._dirty.clear()
        kept = set(self.days)
        archive = self.directory / "archive"
        for path in self.directory.glob("bybit-*.json.gz"):
            if path.name[6:16] not in kept:
                archive.mkdir(parents=True, exist_ok=True)
                os.replace(path, archive / path.name)
        state = {"symbol": self.symbol, "venue": VENUE, "tick": self.tick, "segments": self.segments[-200:], "sessions": self.sessions,
                 "trades": self.trades, "updated_at": self.updated_at, "last_trade_ms": self.last_trade_ms}
        self._write(self.directory / "state.json", json.dumps(state).encode())

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    # --- collecting --------------------------------------------------------------------------

    def connected(self) -> None:
        """A new session: the next trade opens a new stretch."""
        self.sessions += 1
        self._connected = True
        self._flush_order()

    def disconnected(self) -> None:
        self._connected = False
        self._flush_order()
        self.updated_at = datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat()

    def handle_message(self, text: str) -> int:
        """One websocket message. Returns how many trades it carried (0 for pongs and answers)."""
        try:
            message = json.loads(text)
        except ValueError:
            return 0
        if not isinstance(message, dict) or message.get("topic") != TOPIC or not isinstance(message.get("data"), list):
            return 0
        self.messages += 1
        count = 0
        for row in message["data"]:
            try:
                ms, side, price, quantity = int(row["T"]), str(row["S"]), float(row["p"]), float(row["v"])
            except (KeyError, TypeError, ValueError):
                continue
            if side not in ("Buy", "Sell") or quantity <= 0 or price <= 0:
                continue
            self.add(ms, side == "Buy", price, quantity)
            count += 1
        if count:
            self.updated_at = datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat()
        return count

    def add(self, ms: int, taker_buy: bool, price: float, quantity: float) -> None:
        if self.segments and self._connected and ms - self.segments[-1][1] <= SEGMENT_GAP_MS and (self.last_trade_ms or 0) <= ms + 1000:
            self.segments[-1][1] = max(self.segments[-1][1], ms)
        elif self.segments and self.last_trade_ms is not None and ms < self.last_trade_ms - 60_000:
            return  # an old message replayed after a reconnect: already counted
        else:
            self.segments.append([ms, ms])
        self.last_trade_ms = max(self.last_trade_ms or 0, ms)
        self.trades += 1
        key = _day_key(ms)
        bucket = ms // 1000 // BUCKET_SECONDS * BUCKET_SECONDS
        level = round(math.floor(price / self.tick) * self.tick, 8)
        cell = self.days.setdefault(key, {}).setdefault((bucket, level), [0.0, 0.0])
        cell[1 if taker_buy else 0] += quantity
        self._dirty.add(key)
        side = 1.0 if taker_buy else -1.0
        if self._order and self._order[0] == ms and self._order[1] == side:
            self._order[2] += quantity
            self._order[3] += price * quantity
        else:
            self._flush_order()
            self._order = [float(ms), side, quantity, price * quantity]

    def _flush_order(self) -> None:
        order, self._order = self._order, None
        if not order or order[3] < BUBBLE_MIN_USD:
            return
        ms, side, quantity, notional = order
        key = _day_key(int(ms))
        found = self.bubbles.setdefault(key, [])
        found.append([int(ms), round(notional / quantity, 8), round(quantity, 8), int(side)])
        if len(found) > 2 * BUBBLES_PER_DAY:
            found.sort(key=lambda b: b[1] * b[2], reverse=True)
            del found[BUBBLES_PER_DAY:]
            found.sort()
        self._dirty.add(key)

    def prune(self) -> None:
        today = datetime.fromtimestamp(self.clock(), tz=timezone.utc).date()
        oldest = (today - timedelta(days=DAYS_KEPT)).isoformat()
        for key in [k for k in self.days if k < oldest]:
            del self.days[key]
            self.bubbles.pop(key, None)
        oldest_ms = _day_start_ms(today - timedelta(days=DAYS_KEPT))
        self.segments = [s for s in self.segments if s[1] >= oldest_ms] or self.segments[-1:]

    def stale(self) -> bool:
        """Connected but no trade for ``STALE_SECONDS``: the socket is dead."""
        return self._connected and self.last_trade_ms is not None and self.clock() * 1000 - self.last_trade_ms > STALE_SECONDS * 1000

    # --- reading -----------------------------------------------------------------------------

    def rows(self, key: str) -> list[list[float]]:
        return [[b, lv, round(v[0], 6), round(v[1], 6)] for (b, lv), v in sorted(self.days.get(key, {}).items())]

    def covered(self, start_ms: int, end_ms: int) -> bool:
        return any(s[0] <= start_ms and s[1] >= end_ms - 1 for s in self.segments)

    def complete_days(self) -> dict[str, int]:
        return {key: int(self.clock()) for key in self.days
                if self.covered(_day_start_ms(date.fromisoformat(key)), _day_start_ms(date.fromisoformat(key)) + 86_400_000)}

    def store(self) -> dict[str, Any]:
        """Same shape as ``perp_flow.PerpFlow.store`` with ``venue`` and a websocket health block."""
        keys = sorted(self.days)
        bubbles = {k: sorted(sorted(self.bubbles.get(k, []), key=lambda b: b[1] * b[2], reverse=True)[:BUBBLES_PER_DAY]) for k in keys}
        return {"symbol": self.symbol, "market": "perp", "venue": VENUE, "tick": self.tick, "bucket_seconds": BUCKET_SECONDS,
                "source": SOURCE, "updated_at": self.updated_at, "days": {k: self.rows(k) for k in keys}, "bubbles": bubbles,
                "bubble_min_usd": BUBBLE_MIN_USD, "complete": self.complete_days(), "health": self.health()}

    def health(self) -> dict[str, Any]:
        since = self.segments[0][0] if self.segments else None
        return {"since": datetime.fromtimestamp(since / 1000, tz=timezone.utc).isoformat() if since else None,
                "connected": self._connected, "sessions": self.sessions, "segments": len(self.segments), "trades": self.trades,
                "last_trade_at": datetime.fromtimestamp(self.last_trade_ms / 1000, tz=timezone.utc).isoformat() if self.last_trade_ms else None}


def publish(state: Any, store: dict[str, Any]) -> None:
    """Put the store on the dashboard state (caller holds ``state.lock``)."""
    state.bybit_flow = store


async def run_session(flow: BybitFlow, state: Any, connect: Connect, log: Any = None, save_seconds: float = SAVE_SECONDS) -> str:
    """One connection: subscribe, aggregate until the socket ends, save and publish every minute."""
    import asyncio

    note = "closed by server"
    async with connect(WS_URL) as ws:
        flow.connected()
        await ws.send(json.dumps({"op": "subscribe", "args": [TOPIC]}))
        last_save = last_ping = time.monotonic()
        try:
            while True:
                try:
                    text = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    text = None
                if text is not None:
                    if isinstance(text, bytes):
                        text = text.decode("utf-8", "replace")
                    flow.handle_message(text)
                now = time.monotonic()
                if now - last_ping >= CLIENT_PING_SECONDS:
                    last_ping = now
                    await ws.send(json.dumps({"op": "ping"}))
                if now - last_save >= save_seconds:
                    last_save = now
                    flow.prune()
                    await asyncio.to_thread(flow.save)
                    snapshot = flow.store()
                    with state.lock:
                        publish(state, snapshot)
                if flow.stale():
                    note = "no trade for 3 minutes"
                    break
        finally:
            flow.disconnected()
    return note


async def run(state: Any, stop: Any, directory: Path | str = DATA_DIR, log: Any = None, connect: Connect | None = None,
              flow: BybitFlow | None = None, save_seconds: float = SAVE_SECONDS) -> None:
    """Runtime loop (main.py): reconnect forever with growing backoff; every failure is logged, nothing stops."""
    import asyncio

    connect = connect or _default_connect
    flow = flow or BybitFlow(directory)
    try:
        await asyncio.to_thread(flow.load)
        with state.lock:
            publish(state, flow.store())
    except Exception as error:  # noqa: BLE001 - a broken file means a fresh start
        if log:
            log.warning("bybit flow: saved state unreadable, starting fresh: %s: %s", type(error).__name__, error)
    backoff = 1.0
    while not stop.is_set():
        started = time.monotonic()
        try:
            note = await run_session(flow, state, connect, log, save_seconds)
            if log:
                log.info("bybit flow: session ended: %s", note)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - chart data must not stop the runtime
            if log:
                log.warning("bybit flow: %s: %s, reconnecting", type(error).__name__, error)
        try:
            await asyncio.to_thread(flow.save)
            with state.lock:
                publish(state, flow.store())
        except Exception as error:  # noqa: BLE001
            if log:
                log.warning("bybit flow: save failed: %s: %s", type(error).__name__, error)
        if time.monotonic() - started > 60:
            backoff = 1.0
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
        backoff = min(backoff * 2, MAX_BACKOFF_SECONDS)
