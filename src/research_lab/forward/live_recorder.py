"""Live Binance spot aggTrades for the orderflow paper journal, stage B (plan of-live-ps5-2026-11-17, P1).

The recorder follows the public aggTrade id chain over REST (``/api/v3/aggTrades?fromId=``, no key, no orders):
every request starts at the id after the last stored one, so a dropped connection, a restart or a night offline
leaves no hole, it is fetched on the next call. Rows are stored per UTC day in the archive's own column order
(id, price, qty, first_id, last_id, time, is_buyer_maker, is_best_match), so a finished day reduces with the same
code to the same minute bars as the published archive of that day.

A day counts as complete only if its first row was anchored at UTC midnight or follows the previous day without a
break, every id in between is present, and no trade crossed back over midnight. Anything else blocks the day
(``blocked`` in its ``done.json``); a blocked day is never computed silently.

    python -m src.research_lab.forward of-record --root ~/tim-research/of-live/trades [--seconds 600]
"""
from __future__ import annotations

import csv
import fcntl
import json
import os
import time
import urllib.request
from collections.abc import Callable, Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.research_lab.orderflow_ml.bars import (
    MINUTE_MS,
    DayProfile,
    MinuteBar,
    ReductionQuality,
    reduce_trades_with_profile,
    ticks_from_rows,
)

SYMBOL = "BTCUSDT"
REST = "https://api.binance.com/api/v3/aggTrades?symbol={symbol}&fromId={from_id}&limit=1000"
REST_START = "https://api.binance.com/api/v3/aggTrades?symbol={symbol}&startTime={start}&endTime={end}&limit=1"
BATCH = 1000
POLL_SECONDS = 2.0
CATCH_UP_PAUSE = 0.15   # between full batches: about 400 calls/min, weight 4 each, far below 6000/min

Fetch = Callable[[str], Any]


class ChainError(RuntimeError):
    """The REST answer does not continue the id chain; nothing of it is stored."""


def http_json(url: str, timeout: float = 15.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read())


def _day(ms: int) -> date:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date()


def _midnight_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


def _write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def _row(trade: dict) -> list[str]:
    return [str(trade["a"]), trade["p"], trade["q"], str(trade["f"]), str(trade["l"]), str(trade["T"]),
            "True" if trade["m"] else "False", "True" if trade.get("M", True) else "False"]


class TradeRecorder:
    def __init__(self, root: Path | str, symbol: str = SYMBOL, *, fetch: Fetch = http_json,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep) -> None:
        if symbol != SYMBOL:
            raise ValueError("stage B records BTCUSDT spot only (as stage A)")
        self.dir = Path(root) / symbol
        self.symbol = symbol
        self.fetch = fetch
        self.clock = clock
        self.sleep = sleep

    # -- files ------------------------------------------------------------------------------------
    def day_path(self, day: date) -> Path:
        return self.dir / f"{day.isoformat()}.csv"

    def done_path(self, day: date) -> Path:
        return self.dir / f"{day.isoformat()}.done.json"

    def state(self) -> dict | None:
        path = self.dir / "state.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def _save_state(self, state: dict) -> None:
        _write_json(self.dir / "state.json", state)

    # -- chain ------------------------------------------------------------------------------------
    def anchor(self, day: date) -> int:
        """Id of the first trade at or after UTC midnight of ``day`` (the archive's first row of that day)."""
        start = _midnight_ms(day)
        rows = self.fetch(REST_START.format(symbol=self.symbol, start=start, end=start + 3_600_000 - 1))
        if not rows:
            raise ChainError(f"no trade in the first hour of {day}")
        return int(rows[0]["a"])

    def _start(self) -> dict:
        state = self.state()
        if state is None:
            day = _day(int(self.clock() * 1000))
            state = {"day": day.isoformat(), "next_id": self.anchor(day), "day_first_id": None, "day_ok": True,
                     "last_time_ms": None, "started_at_ms": int(self.clock() * 1000)}
            self.dir.mkdir(parents=True, exist_ok=True)
            self._save_state(state)
        return state

    def _close_day(self, state: dict) -> None:
        day = date.fromisoformat(state["day"])
        rows = 0
        if self.day_path(day).exists():
            with self.day_path(day).open(newline="") as handle:
                rows = sum(1 for _ in handle)
        _write_json(self.done_path(day), {"day": state["day"], "first_id": state["day_first_id"],
                                          "last_id": state["next_id"] - 1, "rows": rows,
                                          "complete": bool(state["day_ok"]) and rows > 0,
                                          "closed_at_ms": int(self.clock() * 1000)})

    def _block(self, day: date) -> None:
        path = self.done_path(day)
        done = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"day": day.isoformat()}
        _write_json(path, {**done, "complete": False, "blocked": "trade back across midnight"})

    def poll(self) -> int:
        """One REST call from the next id on; stores the rows and returns how many came."""
        state = self._start()
        batch = self.fetch(REST.format(symbol=self.symbol, from_id=state["next_id"]))
        if not isinstance(batch, list):
            raise ChainError(f"unexpected answer: {str(batch)[:200]}")
        for i, trade in enumerate(batch):
            if int(trade["a"]) != state["next_id"] + i:
                raise ChainError(f"id {trade['a']} where {state['next_id'] + i} was expected")
        by_day: list[tuple[date, list[list[str]]]] = []
        for trade in batch:
            day = _day(int(trade["T"]))
            if by_day and by_day[-1][0] == day:
                by_day[-1][1].append(_row(trade))
            else:
                by_day.append((day, [_row(trade)]))
        for day, rows in by_day:
            current = date.fromisoformat(state["day"])
            if day < current:
                # a trade back across midnight: it belongs to a closed day; both days are no longer the archive's
                self._block(day)
                state["day_ok"] = False
                state["next_id"] = int(rows[-1][0]) + 1
                self._save_state(state)
                continue
            while day > current:
                self._close_day(state)
                current += timedelta(days=1)
                state.update(day=current.isoformat(), day_first_id=None, day_ok=True)
            if state["day_first_id"] is None:
                state["day_first_id"] = int(rows[0][0])
            self.dir.mkdir(parents=True, exist_ok=True)
            with self.day_path(day).open("a", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
            state["next_id"] = int(rows[-1][0]) + 1
            state["last_time_ms"] = max(state["last_time_ms"] or 0, *(int(r[5]) for r in rows))
            self._save_state(state)   # after the rows: a crash in between only repeats rows (dropped as duplicates)
        return len(batch)

    def run(self, *, stop_after: float | None = None, stop_file: Path | None = None) -> dict[str, int]:
        """Poll until ``stop_after`` seconds or the stop file. Network errors back off; chain errors stop."""
        self.dir.mkdir(parents=True, exist_ok=True)
        lock = (self.dir / "record.lock").open("w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ChainError("another recorder already writes this folder") from None
        started = self.clock()
        counts = {"calls": 0, "rows": 0, "errors": 0}
        backoff = POLL_SECONDS
        while (stop_after is None or self.clock() - started < stop_after) and not (stop_file and stop_file.exists()):
            try:
                n = self.poll()
            except ChainError:
                raise
            except Exception as exc:  # noqa: BLE001 - network side: the next call starts at the same id
                counts["errors"] += 1
                print(f"of-record: {type(exc).__name__}: {exc}", flush=True)
                self.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                continue
            backoff = POLL_SECONDS
            counts["calls"] += 1
            counts["rows"] += n
            self._heartbeat(counts)
            self.sleep(CATCH_UP_PAUSE if n == BATCH else POLL_SECONDS)
        return counts

    def _heartbeat(self, counts: dict[str, int]) -> None:
        state = self.state() or {}
        _write_json(self.dir / "status.json", {"pid": os.getpid(), "updated_ms": int(self.clock() * 1000),
                                               "day": state.get("day"), "next_id": state.get("next_id"),
                                               "last_time_ms": state.get("last_time_ms"), "counts": counts})

    # -- read ---------------------------------------------------------------------------------------
    def day_state(self, day: date) -> str:
        """``complete`` (closed, unbroken), ``blocked`` (closed with a break), ``open`` (today) or ``missing``."""
        done = self.done_path(day)
        if done.exists():
            return "complete" if json.loads(done.read_text(encoding="utf-8")).get("complete") else "blocked"
        state = self.state()
        if state and state.get("day") == day.isoformat():
            return "open" if state.get("day_ok") else "blocked"
        return "missing"

    def ticks(self, day: date) -> Iterator:
        """Ticks in id order; rows repeated after a crash (written, state not yet saved) are skipped."""
        last = -1
        with self.day_path(day).open(newline="") as handle:
            for tick in ticks_from_rows(csv.reader(handle)):
                if tick.agg_trade_id > last:
                    last = tick.agg_trade_id
                    yield tick

    def closed_until_ms(self, day: date) -> int | None:
        """Start of the minute of the newest stored trade: every minute before it is complete."""
        state = self.state()
        if not state or state.get("day") != day.isoformat() or not state.get("last_time_ms"):
            return None
        return state["last_time_ms"] // MINUTE_MS * MINUTE_MS

    def reduce(self, day: date, until_ms: int | None = None) -> tuple[list[MinuteBar], ReductionQuality, DayProfile]:
        """Minute bars and profile of a day, or of its minutes before ``until_ms`` (bars cut to those minutes)."""
        start = _midnight_ms(day)
        ticks = self.ticks(day)
        if until_ms is not None:
            ticks = (t for t in ticks if t.time_ms < until_ms)
        bars, quality, profile = reduce_trades_with_profile(ticks, start)
        if until_ms is not None:
            minutes = max(0, min(len(bars), (until_ms - start) // MINUTE_MS))
            bars = bars[:minutes]
            profile = DayProfile(profile.day_start_ms, profile.width_e8,
                                 tuple(e for e in profile.entries if e[0] < minutes))
        return bars, quality, profile

