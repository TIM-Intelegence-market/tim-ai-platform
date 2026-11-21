"""Binance USD-M BTCUSDT perpetual: per closed minute volume, taker buy volume, open interest, funding (paper only).

Uzi 17.11.2026 ("go Futures"): R-ABS-2 should see the futures numbers next to the spot orderflow. Public REST only
(no key, no orders), standard library only (the PS5 venv has no extra packages):

* ``/fapi/v1/klines`` 1m: volume and taker buy volume per closed minute (perp delta = 2 x taker buy - volume).
  After a pause the missing minutes are fetched again from the last stored minute (up to 1000), so the volume
  column has no hole; open interest and funding exist only for minutes polled live and stay empty otherwise.
* ``/fapi/v1/openInterest`` and ``/fapi/v1/premiumIndex``: open interest and last funding rate at the poll.

Rows go to ``<root>/BTCUSDT/<UTC day>.csv``. Liquidations come from the existing S12 collector
(``python -m src.research_lab.liquidations run --data-dir ...``); this module reads both for R-ABS-2.

    python -m src.research_lab.forward futures-record --futures DIR [--seconds N]   # ends on DIR/STOP
"""
from __future__ import annotations

import csv
import json
import time
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SYMBOL = "BTCUSDT"
BASE = "https://fapi.binance.com"
KLINES = BASE + "/fapi/v1/klines?symbol={s}&interval=1m&limit={n}"
KLINES_FROM = BASE + "/fapi/v1/klines?symbol={s}&interval=1m&startTime={t}&limit=1000"
OPEN_INTEREST = BASE + "/fapi/v1/openInterest?symbol={s}"
PREMIUM = BASE + "/fapi/v1/premiumIndex?symbol={s}"
HEADER = ["minute_ms", "volume_btc", "taker_buy_btc", "trades", "close", "oi_btc", "funding_rate", "mark"]
MINUTE_MS = 60_000
POLL_SECONDS = 60.0

Fetch = Callable[[str], Any]


def http_json(url: str, timeout: float = 15.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class FuturesRecorder:
    def __init__(self, root: Path | str, *, fetch: Fetch = http_json, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.dir = Path(root) / SYMBOL
        self.fetch, self.clock, self.sleep = fetch, clock, sleep

    def day_path(self, minute_ms: int) -> Path:
        return self.dir / f"{datetime.fromtimestamp(minute_ms / 1000, tz=timezone.utc).date().isoformat()}.csv"

    def _state(self) -> dict:
        path = self.dir / "state.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def _save_state(self, state: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "state.json.tmp"
        tmp.write_text(json.dumps(state), encoding="utf-8")
        tmp.replace(self.dir / "state.json")

    def poll(self) -> int:
        """One round: closed minutes since the last stored one; OI and funding go on the newest closed minute."""
        now_ms = int(self.clock() * 1000)
        state = self._state()
        last = state.get("last_minute_ms")
        url = KLINES_FROM.format(s=SYMBOL, t=last + MINUTE_MS) if last else KLINES.format(s=SYMBOL, n=3)
        rows = [k for k in self.fetch(url) if int(k[6]) < now_ms and (last is None or int(k[0]) > last)]
        if not rows:
            return 0
        oi = funding = mark = ""
        try:
            oi = str(self.fetch(OPEN_INTEREST.format(s=SYMBOL)).get("openInterest", ""))
            premium = self.fetch(PREMIUM.format(s=SYMBOL))
            funding, mark = str(premium.get("lastFundingRate", "")), str(premium.get("markPrice", ""))
        except Exception as exc:  # noqa: BLE001 - volume rows are kept; OI/funding of this minute stay empty
            print(f"futures: OI/Funding fehlt ({type(exc).__name__}: {exc})", flush=True)
        self.dir.mkdir(parents=True, exist_ok=True)
        for i, k in enumerate(rows):
            newest = i == len(rows) - 1 and now_ms - int(k[6]) < 2 * MINUTE_MS
            path = self.day_path(int(k[0]))
            new = not path.exists()
            with path.open("a", newline="") as handle:
                writer = csv.writer(handle)
                if new:
                    writer.writerow(HEADER)
                writer.writerow([int(k[0]), k[5], k[9], k[8], k[4], oi if newest else "", funding if newest else "",
                                 mark if newest else ""])
        state["last_minute_ms"] = int(rows[-1][0])
        state["updated_ms"] = now_ms
        self._save_state(state)
        return len(rows)

    def run(self, *, stop_after: float | None = None, stop_file: Path | None = None) -> dict[str, int]:
        started, counts = self.clock(), {"calls": 0, "rows": 0, "errors": 0}
        while not (stop_file and stop_file.exists()) and (stop_after is None or self.clock() - started < stop_after):
            try:
                counts["rows"] += self.poll()
            except Exception as exc:  # noqa: BLE001 - logged, next round tries again
                counts["errors"] += 1
                print(f"futures: {datetime.now(timezone.utc).isoformat()} {type(exc).__name__}: {exc}", flush=True)
            counts["calls"] += 1
            self.sleep(POLL_SECONDS)
        return counts


# -- reading (R-ABS-2) --------------------------------------------------------------------------------------------
def read_rows(root: Path | str, start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    """Stored minutes with ``start_ms <= minute < end_ms``; later duplicates of a minute are ignored."""
    folder = Path(root) / SYMBOL
    days = sorted({datetime.fromtimestamp(t / 1000, tz=timezone.utc).date()
                   for t in range(start_ms // 86_400_000 * 86_400_000, end_ms, 86_400_000)})
    out: dict[int, dict[str, Any]] = {}
    for day in days:
        path = folder / f"{day.isoformat()}.csv"
        if not path.exists():
            continue
        with path.open(newline="") as handle:
            for row in csv.DictReader(handle):
                minute = int(row["minute_ms"])
                if start_ms <= minute < end_ms and minute not in out:
                    out[minute] = row
    return [out[m] for m in sorted(out)]


def _num(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def context(futures_root: Path | str | None, liq_root: Path | str | None, start_ms: int, end_ms: int) -> dict[str, Any] | None:
    """Futures numbers of a closed window [start_ms, end_ms): perp delta, OI change over 60 min, funding, liquidations."""
    if futures_root is None and liq_root is None:
        return None
    out: dict[str, Any] = {}
    if futures_root is not None:
        window = read_rows(futures_root, start_ms, end_ms)
        hour = read_rows(futures_root, end_ms - 60 * MINUTE_MS, end_ms)
        if window:
            vol = sum(_num(r["volume_btc"]) or 0 for r in window)
            buy = sum(_num(r["taker_buy_btc"]) or 0 for r in window)
            out["perp_volumen_btc"] = round(vol, 3)
            out["perp_delta_btc"] = round(2 * buy - vol, 3)
        ois = [(int(r["minute_ms"]), _num(r["oi_btc"])) for r in hour if _num(r["oi_btc"]) is not None]
        if len(ois) >= 2:
            out["oi_aenderung_60m_pct"] = round((ois[-1][1] - ois[0][1]) / ois[0][1] * 100, 3)
        funding = [_num(r["funding_rate"]) for r in hour if _num(r["funding_rate"]) is not None]
        if funding:
            out["funding_rate"] = funding[-1]
        if not window:
            out["perp_fehlt"] = True
    if liq_root is not None:
        from src.research_lab.liquidations import events, store

        long_usd = short_usd = 0.0
        found = False
        for venue, parse in events.PARSERS.items():
            for record in store.records_between(Path(liq_root), venue, start_ms * 1_000_000, end_ms * 1_000_000):
                if record.get("kind") != "message" or not record.get("payload"):
                    continue
                found = True
                try:
                    parsed = parse(json.loads(record["payload"]))
                except (ValueError, events.EventFormatError):
                    continue
                for event in parsed:
                    if event.counts and event.symbol == SYMBOL:
                        if event.side == events.LONG:
                            long_usd += float(event.notional)
                        else:
                            short_usd += float(event.notional)
        out["liq_long_usd"] = round(long_usd)   # liquidated longs = forced selling
        out["liq_short_usd"] = round(short_usd)  # liquidated shorts = forced buying
        out["liq_nachrichten"] = found   # False: no message in the window (none, or collector down)
    return out
