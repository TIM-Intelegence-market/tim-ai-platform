"""BTC perpetual (Binance USD-M futures) trades and open interest for the TIM chart (display only).

Broncx reads orderflow on the perp: its volume is 8-12x the spot volume and its delta can run
against the spot delta (Beirat 29.10.2026: +2534 BTC spot vs. -1844 BTC perp on 27.10.). TIM
stores spot trades in PostgreSQL; this module adds the perp side without touching that path:

- ``PerpFlow`` reads ``/fapi/v1/aggTrades`` by ``fromId``: every aggregate trade id follows the
  last one, so the record has no holes as long as the ids run on (the 48-h test of 29.10.2026:
  525,663 trades, 0 gaps, every full hour equal to Binance's 1h candle in volume and taker delta).
  Trades are aggregated at once into the footprint store's rows ``[bucket, level, bid, ask]``
  (5-minute buckets, 5 $ levels) plus large taker orders for the bubbles; no raw trade is kept.
- The rows are saved per UTC day under ``data/perp_flow/`` together with the next id. After a
  restart the runtime goes on from that id and catches up, so a restart leaves no gap either.
- Once an hour the last full hours are compared with Binance's 1h perp candle (volume and taker
  buy volume). The result is shown on the chart, so a broken record cannot hide.
- ``open_interest`` reads the hourly open interest history and adds the Z-score over 7.5 days
  (180 hours), the window Broncx uses.

Nothing here trades, writes a plan or changes a score. Public endpoints only, no key, no account.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import statistics
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

FAPI = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"
TICK = 5.0  # same price level as the spot store (footprint_data.TICK_BY_SYMBOL)
BUCKET_SECONDS = 300
DAYS_KEPT = 14
BATCH = 1000  # aggTrades per call (Binance maximum), request weight 20
BACKFILL_DAYS = 1  # a fresh start reads from 00:00 UTC of the previous day, so yesterday's profile is complete
CALLS_PER_MINUTE = 60  # 1200 of Binance's 2400 weight per minute at most, while catching up
IDLE_SECONDS = 2.0  # pause after a call that brought less than a full batch (caught up)
SAVE_SECONDS = 60
CHECK_HOURS = 3  # full hours compared with Binance's 1h candle on every check
CHECK_KEEP = 48
CHECK_TOLERANCE = 0.01  # BTC: Binance rounds the candle volume to 3 decimals
BUBBLE_MIN_USD = 100_000.0  # same floor as the spot bubbles (footprint_data.BUBBLE_MIN_USD)
BUBBLES_PER_DAY = 2000
OI_PERIOD = "1h"
OI_LIMIT = 500  # about 20 days of hourly open interest (Binance keeps 30 days)
OI_WINDOW = 180  # 7.5 days of hours: the Z-score window Broncx uses
OI_STALE_AFTER = timedelta(hours=3)
TIMEOUT_SECONDS = 15
MAX_BYTES = 8_000_000
SOURCE = "Binance USD-M Perp aggTrades (BTCUSDT, öffentlich, TIM-Sammler)"
OI_SOURCE = "Binance USD-M Open Interest (BTCUSDT, 1h, öffentlich)"
DATA_DIR = Path("data/perp_flow")

Fetch = Callable[[str, Mapping[str, str]], Any]


class RateLimited(RuntimeError):
    """Binance answered 418/429: the caller waits before the next call."""


def fetch_json(path: str, params: Mapping[str, str]) -> Any:
    url = f"{FAPI}{path}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": "TIM-ControlCenter/1 (read-only)"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 - fixed https host
            body = response.read(MAX_BYTES + 1)
    except HTTPError as error:
        if error.code in (418, 429):
            raise RateLimited(f"binance http {error.code}") from error
        raise
    if len(body) > MAX_BYTES:
        raise ValueError("binance response too large")
    return json.loads(body)


def _day_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _day_start_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


class PerpFlow:
    """Gapless perp trade record, aggregated for the chart. Not thread-safe: one runner calls it."""

    def __init__(self, directory: Path | str = DATA_DIR, fetch: Fetch | None = None,
                 clock: Callable[[], float] | None = None, symbol: str = SYMBOL) -> None:
        self.directory = Path(directory)
        self.fetch = fetch or fetch_json
        self.clock = clock or time.time
        self.symbol = symbol
        self.days: dict[str, dict[tuple[int, float], list[float]]] = {}
        self.bubbles: dict[str, list[list[float]]] = {}
        self.next_id: int | None = None
        self.segments: list[list[int]] = []  # [first_ms, last_ms] of each stretch read without a hole
        self.gaps: list[dict[str, Any]] = []
        self.checks: list[dict[str, Any]] = []
        self.calls = 0
        self.updated_at: str | None = None
        self._dirty: set[str] = set()
        # Per day: the next id at the day file's last save. A crash between saving the day files and
        # state.json resumes from the older id; trades below a day's mark are in that file already.
        self.upto: dict[str, int] = {}
        self._order: list[float] | None = None  # running taker order [ms, side, quantity, notional]

    # --- persistence -------------------------------------------------------------------------

    def load(self) -> None:
        state_file = self.directory / "state.json"
        if not state_file.exists():
            return
        state = json.loads(state_file.read_text())
        if state.get("symbol") != self.symbol or float(state.get("tick", TICK)) != TICK:
            return
        self.next_id = state.get("next_id")
        self.segments = [list(map(int, s)) for s in state.get("segments") or []]
        self.gaps = list(state.get("gaps") or [])
        self.checks = list(state.get("checks") or [])
        self.updated_at = state.get("updated_at")
        for path in sorted(self.directory.glob("perp-*.json.gz")):
            try:
                payload = json.loads(gzip.decompress(path.read_bytes()))
            except (OSError, ValueError):
                continue
            key = payload["day"]
            self.days[key] = {(int(b), float(lv)): [float(bid), float(ask)] for b, lv, bid, ask in payload["rows"]}
            self.bubbles[key] = [list(map(float, row)) for row in payload.get("bubbles") or []]
            self.upto[key] = int(payload.get("upto") or 0)

    def save(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        for key in sorted(self._dirty):
            if key not in self.days:
                continue
            payload = {"day": key, "symbol": self.symbol, "tick": TICK, "bucket_seconds": BUCKET_SECONDS,
                       "rows": self.rows(key), "bubbles": self.bubbles.get(key, []), "upto": self.next_id}
            self._write(self.directory / f"perp-{key}.json.gz", gzip.compress(json.dumps(payload).encode()))
        self._dirty.clear()
        kept = set(self.days)
        for path in self.directory.glob("perp-*.json.gz"):
            if path.name[5:15] not in kept:
                path.unlink(missing_ok=True)
        state = {"symbol": self.symbol, "tick": TICK, "next_id": self.next_id, "segments": self.segments,
                 "gaps": self.gaps[-50:], "checks": self.checks[-CHECK_KEEP:], "updated_at": self.updated_at}
        self._write(self.directory / "state.json", json.dumps(state).encode())

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    # --- collecting --------------------------------------------------------------------------

    def _first_id_from(self, start_ms: int) -> int | None:
        rows = self.fetch("/fapi/v1/aggTrades", {"symbol": self.symbol, "startTime": str(start_ms),
                                                 "endTime": str(start_ms + 3_600_000 - 1), "limit": "1"})
        self.calls += 1
        return int(rows[0]["a"]) if isinstance(rows, list) and rows else None

    def start_point(self) -> None:
        """Where to read from: the saved next id, or (fresh start or too old) 00:00 UTC of yesterday."""
        now_ms = int(self.clock() * 1000)
        oldest_ms = now_ms - (DAYS_KEPT - 1) * 86_400_000
        if self.next_id is not None and self.segments and self.segments[-1][1] >= oldest_ms:
            return
        day = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).date() - timedelta(days=BACKFILL_DAYS)
        start_ms = _day_start_ms(day)
        first = None
        while first is None and start_ms < now_ms:
            first = self._first_id_from(start_ms)
            if first is None:
                start_ms += 3_600_000
        if first is None:
            raise ValueError("perp: no aggTrade found to start from")
        if self.next_id is not None:
            self.gaps.append({"after_id": self.next_id - 1, "resume_id": first, "at": datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc).isoformat(),
                              "reason": "Stand zu alt, neu begonnen"})
        self.next_id = first
        self.segments.append([start_ms, start_ms])

    def step(self) -> int:
        """One call: the next ``BATCH`` trades from ``next_id``. Returns how many came."""
        if self.next_id is None:
            self.start_point()
        rows = self.fetch("/fapi/v1/aggTrades", {"symbol": self.symbol, "fromId": str(self.next_id), "limit": str(BATCH)})
        self.calls += 1
        if not isinstance(rows, list):
            raise ValueError("perp aggTrades: answer is not a list")
        for row in rows:
            self._add(row)
        if len(rows) < BATCH and self.segments:
            # Caught up: the record reaches up to now even when the market was quiet.
            self.segments[-1][1] = max(self.segments[-1][1], int(self.clock() * 1000) - 1000)
            self._flush_order()  # while catching up an order may go on in the next batch
        self.updated_at = datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat()
        self.prune()
        return len(rows)

    def _add(self, row: Mapping[str, Any]) -> None:
        agg_id, price, quantity, ms = int(row["a"]), float(row["p"]), float(row["q"]), int(row["T"])
        seller_aggressive = bool(row["m"])  # buyer is maker: the seller hit the bid
        if agg_id < self.next_id:
            return  # already counted (overlap after a restart)
        if agg_id > self.next_id:
            self.gaps.append({"after_id": self.next_id - 1, "resume_id": agg_id,
                              "at": datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(), "reason": "Id-Lücke bei Binance"})
            self.segments.append([ms, ms])
        if not self.segments:
            self.segments.append([ms, ms])
        self.next_id = agg_id + 1
        self.segments[-1][1] = max(self.segments[-1][1], ms)
        key = _day_key(ms)
        if agg_id < self.upto.get(key, 0):
            return  # counted in the saved day file already
        bucket = ms // 1000 // BUCKET_SECONDS * BUCKET_SECONDS
        level = round(math.floor(price / TICK) * TICK, 8)
        cell = self.days.setdefault(key, {}).setdefault((bucket, level), [0.0, 0.0])
        cell[0 if seller_aggressive else 1] += quantity
        self._dirty.add(key)
        side = -1.0 if seller_aggressive else 1.0
        if self._order and self._order[0] == ms and self._order[1] == side:
            self._order[2] += quantity
            self._order[3] += price * quantity
        else:
            self._flush_order()
            self._order = [float(ms), side, quantity, price * quantity]

    def _flush_order(self) -> None:
        """A finished taker order (same ms and side) above the floor becomes a bubble."""
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
            self.upto.pop(key, None)
        oldest_ms = _day_start_ms(today - timedelta(days=DAYS_KEPT))
        self.segments = [s for s in self.segments if s[1] >= oldest_ms] or self.segments[-1:]

    # --- reading -----------------------------------------------------------------------------

    def rows(self, key: str) -> list[list[float]]:
        return [[b, lv, round(v[0], 6), round(v[1], 6)] for (b, lv), v in sorted(self.days.get(key, {}).items())]

    def covered(self, start_ms: int, end_ms: int) -> bool:
        return any(s[0] <= start_ms and s[1] >= end_ms - 1 for s in self.segments)

    def complete_days(self) -> dict[str, int]:
        result = {}
        for key in self.days:
            start = _day_start_ms(date.fromisoformat(key))
            if self.covered(start, start + 86_400_000):
                result[key] = int(self.clock())
        return result

    def store(self) -> dict[str, Any]:
        """Same shape as ``DashboardState.footprint`` (footprint_data.refresh), plus the record's health."""
        keys = sorted(self.days)
        bubbles = {k: sorted(sorted(self.bubbles.get(k, []), key=lambda b: b[1] * b[2], reverse=True)[:BUBBLES_PER_DAY]) for k in keys}
        return {"symbol": self.symbol, "market": "perp", "tick": TICK, "bucket_seconds": BUCKET_SECONDS, "source": SOURCE,
                "updated_at": self.updated_at, "days": {k: self.rows(k) for k in keys}, "bubbles": bubbles,
                "bubble_min_usd": BUBBLE_MIN_USD, "complete": self.complete_days(), "health": self.health()}

    def health(self) -> dict[str, Any]:
        checked = [c for c in self.checks if c.get("ok") is not None]
        since = self.segments[0][0] if self.segments else None
        return {"since": datetime.fromtimestamp(since / 1000, tz=timezone.utc).isoformat() if since else None,
                "next_id": self.next_id, "gaps": len(self.gaps), "last_gap": self.gaps[-1] if self.gaps else None,
                "checks": len(checked), "checks_ok": sum(1 for c in checked if c["ok"]), "last_check": checked[-1] if checked else None,
                "calls": self.calls}

    def hour_totals(self, hour_start: int) -> tuple[float, float]:
        """Volume and taker buy volume of one hour (epoch seconds) from the stored rows."""
        key = datetime.fromtimestamp(hour_start, tz=timezone.utc).date().isoformat()
        volume = buy = 0.0
        for (bucket, _), (bid, ask) in self.days.get(key, {}).items():
            if hour_start <= bucket < hour_start + 3600:
                volume += bid + ask
                buy += ask
        return volume, buy

    def check(self) -> list[dict[str, Any]]:
        """Compare the last full, completely read hours with Binance's 1h perp candle."""
        now = int(self.clock())
        last_full = now // 3600 * 3600 - 3600
        done = {c["hour"] for c in self.checks}
        wanted = [h for h in range(last_full - (CHECK_HOURS - 1) * 3600, last_full + 1, 3600)
                  if self.covered(h * 1000, (h + 3600) * 1000)
                  and datetime.fromtimestamp(h, tz=timezone.utc).isoformat() not in done]
        if not wanted:
            return []
        candles = self.fetch("/fapi/v1/klines", {"symbol": self.symbol, "interval": "1h", "startTime": str(wanted[0] * 1000),
                                                 "endTime": str(wanted[-1] * 1000 + 3_599_999), "limit": str(len(wanted) + 1)})
        self.calls += 1
        by_time = {int(row[0]) // 1000: row for row in candles if isinstance(row, list) and len(row) > 9}
        results = []
        for hour in wanted:
            if hour not in by_time:
                continue
            volume, buy = self.hour_totals(hour)
            k_volume, k_buy = float(by_time[hour][5]), float(by_time[hour][9])
            delta, k_delta = 2 * buy - volume, 2 * k_buy - k_volume
            ok = abs(volume - k_volume) <= CHECK_TOLERANCE and abs(delta - k_delta) <= 2 * CHECK_TOLERANCE
            results.append({"hour": datetime.fromtimestamp(hour, tz=timezone.utc).isoformat(), "volume": round(volume, 3),
                            "binance_volume": k_volume, "delta": round(delta, 3), "binance_delta": round(k_delta, 3), "ok": ok})
        self.checks = (self.checks + results)[-CHECK_KEEP:]
        return results


def zscores(values: Sequence[float], window: int = OI_WINDOW) -> list[float | None]:
    """Rolling Z-score: (value - mean) / standard deviation of the last ``window`` values, itself included."""
    result: list[float | None] = []
    for index in range(len(values)):
        if index + 1 < window:
            result.append(None)
            continue
        part = values[index + 1 - window:index + 1]
        spread = statistics.pstdev(part)
        result.append(round((values[index] - statistics.fmean(part)) / spread, 3) if spread > 0 else 0.0)
    return result


def open_interest(fetch: Fetch | None = None, symbol: str = SYMBOL, now: datetime | None = None) -> dict[str, Any]:
    """Hourly open interest (BTC and USD) of the last ~20 days with its 7.5-day Z-score."""
    fetch = fetch or fetch_json
    rows = fetch("/futures/data/openInterestHist", {"symbol": symbol, "period": OI_PERIOD, "limit": str(OI_LIMIT)})
    if not isinstance(rows, list):
        raise ValueError("open interest: answer is not a list")
    points = []
    for row in rows:
        try:
            points.append((int(row["timestamp"]) // 1000, float(row["sumOpenInterest"]), float(row["sumOpenInterestValue"])))
        except (KeyError, TypeError, ValueError):
            continue
    points.sort()
    if len(points) < 2:
        raise ValueError("open interest: fewer than two points")
    scores = zscores([p[1] for p in points])
    return {"symbol": symbol, "period": OI_PERIOD, "window_hours": OI_WINDOW, "source": OI_SOURCE,
            "as_of": (now or datetime.now(timezone.utc)).isoformat(),
            "points": [[t, round(oi, 3), round(usd, 0)] for t, oi, usd in points],
            "z": [[p[0], z] for p, z in zip(points, scores) if z is not None]}


def oi_chart(snapshot: Mapping[str, Any] | None, first_time: int, now: datetime | None = None) -> dict[str, Any] | None:
    """The part of the open interest the chart shows: from one hour before the first candle on."""
    if not snapshot or not snapshot.get("points"):
        return None
    now = now or datetime.now(timezone.utc)
    stale = now - datetime.fromisoformat(str(snapshot["as_of"])) > OI_STALE_AFTER
    start = first_time - 3600
    last_z = snapshot["z"][-1][1] if snapshot.get("z") else None
    return {"points": [[t, oi] for t, oi, _ in snapshot["points"] if t >= start], "z": [p for p in snapshot.get("z") or [] if p[0] >= start],
            "last": snapshot["points"][-1][1], "last_usd": snapshot["points"][-1][2], "last_z": last_z,
            "window_hours": snapshot.get("window_hours", OI_WINDOW), "as_of": snapshot["as_of"], "stale": stale, "source": snapshot.get("source")}


async def run(state: Any, stop: Any, directory: Path | str = DATA_DIR, log: Any = None,
              flow: PerpFlow | None = None, oi_fetch: Fetch | None = None) -> None:
    """Runtime loop (main.py): collect, check, save and publish to ``state.perp_flow`` / ``state.open_interest``.

    Display only, never on TIM's ingestion path: every failure is logged and retried later.
    """
    import asyncio

    flow = flow or PerpFlow(directory)
    try:
        await asyncio.to_thread(flow.load)
    except Exception as error:  # noqa: BLE001 - a broken file means a fresh start, not a stopped runtime
        if log:
            log.warning("perp flow: saved state unreadable, starting fresh: %s: %s", type(error).__name__, error)
    last_save = last_check = last_oi = 0.0
    published = False
    while not stop.is_set():
        pause = 60.0 / CALLS_PER_MINUTE
        try:
            if await asyncio.to_thread(flow.step) < BATCH:
                pause = IDLE_SECONDS
                if not published:
                    last_save = 0.0  # caught up for the first time: show it at once
            now = flow.clock()
            if now - last_check >= 600:
                last_check = now
                await asyncio.to_thread(flow.check)
            if now - last_save >= SAVE_SECONDS:
                last_save = now
                await asyncio.to_thread(flow.save)
                snapshot = await asyncio.to_thread(flow.store)
                with state.lock:
                    state.perp_flow = snapshot
                published = published or pause == IDLE_SECONDS
        except asyncio.CancelledError:
            raise
        except RateLimited as error:
            pause = 60.0
            if log:
                log.warning("perp flow: %s, waiting 60 s", error)
        except Exception as error:  # noqa: BLE001 - chart data must not stop the runtime
            pause = 30.0
            if log:
                log.warning("perp flow failed: %s: %s", type(error).__name__, error)
        if flow.clock() - last_oi >= 300:
            last_oi = flow.clock()
            try:
                snapshot = await asyncio.to_thread(open_interest, oi_fetch)
                with state.lock:
                    state.open_interest = snapshot
            except asyncio.CancelledError:
                raise
            except Exception as error:  # noqa: BLE001
                if log:
                    log.warning("open interest refresh failed: %s: %s", type(error).__name__, error)
        try:
            await asyncio.wait_for(stop.wait(), timeout=pause)
        except TimeoutError:
            pass
    try:
        await asyncio.to_thread(flow.save)
    except Exception:  # noqa: BLE001
        pass
