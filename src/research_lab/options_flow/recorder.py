"""A1: Deribit options-flow recorder (public REST, no key, read-only, nothing is ordered).

Polls three public endpoints and stores every answer unchanged with the local receive time, in the same gzip JSONL
segment layout as the Bitunix recorder (``<root>/<CUR>OPT<STREAM>/<YYYY-MM-DD>.<run_start_ms>.jsonl.gz``):

- ``TRADES``  : ``get_last_trades_by_currency_and_time`` (kind=option), every ``TRADES_POLL_S`` seconds, paged.
- ``SUMMARY`` : ``get_book_summary_by_currency`` (open interest, mark IV, volume per instrument), every ``SLOW_POLL_S``.
- ``DVOL``    : ``get_volatility_index_data``, every ``SLOW_POLL_S``.

Safety and health (same rules as the Bitunix recorder, PR #226):
- Network and API errors are counted and retried at the next poll; the cursor does not move, so the next successful
  poll asks again from the same point and a short outage is filled if Deribit still serves that period.
- Storage errors (disk full, permissions) are fatal: ``status.json`` gets ``state: failed``, exit code 2, so launchd
  restarts the run and the hole stays visible. Below ``min_free_bytes`` free space it stops the same way.
- ``status.json`` holds the heartbeat, counters and the trade cursor. On start a ``gap`` row from the last receive
  time is written, so restarts leave a marked hole.
- Only the three fixed Deribit methods above are called, only HTTPS GET to www.deribit.com, no key, no account.

Unverified (cloud egress blocks Deribit): parameter names and response layout follow the Deribit v2 docs; the first
run on the Mac must be checked with ``audit`` (see the data contract). Raw rows make a later parser fix possible.

    python -m src.research_lab.options_flow record --root ~/TIM-research/options-flow [--currency BTC]
"""
from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.research_lab.bitunix.recorder import DayWriter, StorageError

DERIBIT_PUBLIC = "https://www.deribit.com/api/v2/public"
TRADES_POLL_S = 10.0
SLOW_POLL_S = 300.0
PAGE_COUNT = 1000
MAX_PAGES = 20
MIN_FREE_BYTES = 2 * 1024**3
TIMEOUT_S = 20
MAX_BYTES = 16_000_000
CURRENCIES = ("BTC", "ETH")
USER_AGENT = "TIM-options-flow-recorder/1 (read-only)"

Fetch = Callable[[str, Mapping[str, Any]], Any]


def fetch_json(method: str, params: Mapping[str, Any]) -> Any:
    url = f"{DERIBIT_PUBLIC}/{method}?{urlencode(params)}"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=TIMEOUT_S) as response:
        body = response.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("deribit response too large")
    return json.loads(body)


def _result(payload: Any, label: str) -> Any:
    if not isinstance(payload, Mapping) or "result" not in payload:
        raise ValueError(f"deribit {label}: no result")
    return payload["result"]


def streams(currency: str) -> dict[str, str]:
    if currency not in CURRENCIES:
        raise ValueError(f"currency {currency!r} not allowed")
    return {k: f"{currency}OPT{k}" for k in ("TRADES", "SUMMARY", "DVOL")}


class Cursor:
    """Trade cursor: last exchange timestamp seen and the trade ids already stored at exactly that millisecond."""

    def __init__(self, ts_ms: int | None = None, ids: set[str] | None = None) -> None:
        self.ts_ms = ts_ms
        self.ids = ids or set()

    def accept(self, trade: Mapping[str, Any]) -> bool:
        ts, tid = trade.get("timestamp"), trade.get("trade_id")
        if not isinstance(ts, int) or not isinstance(tid, str):
            return True  # stored raw anyway; the contract rejects it later and counts it
        if self.ts_ms is not None and ts < self.ts_ms:
            return False
        return not (ts == self.ts_ms and tid in self.ids)

    def advance(self, trade: Mapping[str, Any]) -> None:
        ts, tid = trade.get("timestamp"), trade.get("trade_id")
        if not isinstance(ts, int) or not isinstance(tid, str):
            return
        if self.ts_ms is None or ts > self.ts_ms:
            self.ts_ms, self.ids = ts, {tid}
        elif ts == self.ts_ms:
            self.ids.add(tid)

    def dump(self) -> dict[str, Any]:
        return {"ts_ms": self.ts_ms, "ids": sorted(self.ids)}

    @classmethod
    def load(cls, data: Any) -> Cursor:
        if isinstance(data, Mapping) and isinstance(data.get("ts_ms"), int):
            return cls(data["ts_ms"], {i for i in data.get("ids", []) if isinstance(i, str)})
        return cls()


class Status:
    def __init__(self, root: Path) -> None:
        self.path = root / "status.json"

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise StorageError(f"status unreadable: {exc}") from exc
        return data if isinstance(data, dict) else {}

    def write(self, state: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(state, separators=(",", ":")))
            os.replace(tmp, self.path)
        except OSError as exc:
            raise StorageError(f"status write: {exc}") from exc


def poll_trades(currency: str, cursor: Cursor, writer: DayWriter, fetch: Fetch, now_ms: int, recv: Callable[[], int],
                counts: dict[str, int], backfill_ms: int = 3_600_000) -> None:
    """One paged poll. The cursor only advances over rows already written to disk."""
    stream = streams(currency)["TRADES"]
    start = cursor.ts_ms if cursor.ts_ms is not None else now_ms - backfill_ms
    for _ in range(MAX_PAGES):
        payload = _result(fetch("get_last_trades_by_currency_and_time", {
            "currency": currency, "kind": "option", "start_timestamp": start, "end_timestamp": now_ms,
            "count": PAGE_COUNT, "sorting": "asc", "include_old": "true"}), "trades")
        trades = payload.get("trades") if isinstance(payload, Mapping) else None
        if not isinstance(trades, list):
            raise TypeError("deribit trades: no trades list")
        fresh = 0
        for trade in trades:
            if not isinstance(trade, Mapping) or not cursor.accept(trade):
                counts["duplicates_skipped"] += 1
                continue
            r = recv()
            writer.write(stream, {"kind": "trade", "recv_ms": r, "raw": trade}, r)
            cursor.advance(trade)
            counts["trades"] += 1
            fresh += 1
        has_more = bool(payload.get("has_more"))
        if not has_more or cursor.ts_ms is None:
            return
        if fresh == 0:  # page full of already-seen rows at one millisecond: step over it instead of looping
            cursor.ts_ms += 1
            cursor.ids = set()
            counts["cursor_skips"] += 1
        start = cursor.ts_ms
    counts["page_limit_hits"] += 1


def poll_slow(currency: str, writer: DayWriter, fetch: Fetch, now_ms: int, recv: Callable[[], int],
              counts: dict[str, int]) -> None:
    s = streams(currency)
    summary = _result(fetch("get_book_summary_by_currency", {"currency": currency, "kind": "option"}), "summary")
    if not isinstance(summary, list):
        raise TypeError("deribit summary: result is not a list")
    r = recv()
    writer.write(s["SUMMARY"], {"kind": "summary", "recv_ms": r, "result": summary}, r)
    counts["summaries"] += 1
    dvol = _result(fetch("get_volatility_index_data", {
        "currency": currency, "start_timestamp": now_ms - 2 * 3_600_000, "end_timestamp": now_ms,
        "resolution": "60"}), "dvol")
    r = recv()
    writer.write(s["DVOL"], {"kind": "dvol", "recv_ms": r, "result": dvol}, r)
    counts["dvol"] += 1


def free_bytes(root: Path) -> int:
    return shutil.disk_usage(root).free


def record(root: Path, currency: str = "BTC", *, stop_after: float | None = None, fetch: Fetch = fetch_json,
           clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
           min_free_bytes: int = MIN_FREE_BYTES, disk_free: Callable[[Path], int] = free_bytes) -> dict[str, int]:
    """Record until ``stop_after`` seconds (None = forever). StorageError propagates after status ``failed``."""
    s = streams(currency)
    root.mkdir(parents=True, exist_ok=True)
    status = Status(root)
    prev = status.load()
    writer = DayWriter(root, list(s.values()), run_id=int(clock() * 1000))
    cursor = Cursor.load(prev.get("cursor"))
    counts = dict.fromkeys(("trades", "duplicates_skipped", "cursor_skips", "page_limit_hits", "summaries", "dvol",
                            "gaps", "errors", "consecutive_errors"), 0)
    started = clock()
    last_ok_ms = prev.get("last_recv_ms") if isinstance(prev.get("last_recv_ms"), int) else None
    last_error = ""
    next_slow = 0.0

    def recv() -> int:
        nonlocal last_ok_ms
        last_ok_ms = int(clock() * 1000)
        return last_ok_ms

    def heartbeat(state: str) -> None:
        free = disk_free(root)
        status.write({"state": state, "pid": os.getpid(), "currency": currency, "updated_ms": int(clock() * 1000),
                      "last_recv_ms": last_ok_ms, "cursor": cursor.dump(), "free_bytes": free, "counts": counts,
                      "last_error": last_error})
        if free < min_free_bytes:
            raise StorageError(f"free space {free} below {min_free_bytes}")

    try:
        heartbeat("starting")
        if last_ok_ms is not None:
            now_ms = int(clock() * 1000)
            writer.write(s["TRADES"], {"kind": "gap", "from_ms": last_ok_ms, "to_ms": now_ms}, now_ms)
            counts["gaps"] += 1
        while stop_after is None or clock() - started < stop_after:
            now_ms = int(clock() * 1000)
            try:
                poll_trades(currency, cursor, writer, fetch, now_ms, recv, counts)
                if clock() >= next_slow:
                    poll_slow(currency, writer, fetch, now_ms, recv, counts)
                    next_slow = clock() + SLOW_POLL_S
                counts["consecutive_errors"] = 0
            except StorageError:
                raise
            except Exception as exc:  # noqa: BLE001 - network/API side; storage errors re-raised above
                counts["errors"] += 1
                counts["consecutive_errors"] += 1
                last_error = f"{type(exc).__name__}: {exc}"[:300]
                print(f"options-flow recorder: {last_error}", flush=True)
            writer.flush()
            heartbeat("running")
            sleep(min(TRADES_POLL_S * (1 + min(counts["consecutive_errors"], 6)), 120.0))
        writer.close()
        heartbeat("stopped")
    except StorageError as exc:
        try:
            status.write({"state": "failed", "error": str(exc), "updated_ms": int(clock() * 1000),
                          "last_recv_ms": last_ok_ms, "cursor": cursor.dump(), "counts": counts})
        except StorageError:
            pass
        raise
    finally:
        try:
            writer.close()
        except StorageError:
            pass
    return counts


