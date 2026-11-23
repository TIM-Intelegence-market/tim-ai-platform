"""S40 package 1: load the public archives for 2020-2024 and write the data-maturity report. Reads and writes only
below ``--ziel``; touches no live service.

Plan: ``docs/research_lab/studien/S40_ORDERFLOW_OPTIONSFLOW_HISTORISCH_PRAEREGISTRIERUNG_ENTWURF.md`` section 4.
Uzi 23.11.2026: "historisch ja", "go daten".

- Binance USD-M daily ``aggTrades`` per market and day: verified against the official ``.CHECKSUM`` sidecar, streamed
  into 5-minute bars (open, high, low, close, aggressive buy and sell volume, trade count, time of the last trade) and
  the gaps of more than 10 minutes without a trade. The raw zip is not kept (a BTC day is 100-300 MB).
- Binance monthly ``fundingRate`` per market: kept as published (small).
- Deribit BTC option trades from ``history.deribit.com`` per UTC day: the fields S40 needs, as ``jsonl.gz``.

The holdout lock holds at every step: a day or month from 2025-01-01 is refused before any request, and every trade
time passes ``historisch.to_ms`` and the holdout check again. The run is resumable: finished days are skipped.

    python -m src.research_lab.studies.s40_daten laden --ziel ~/tim-research/data/s40 [--teil binance|funding|deribit]
    python -m src.research_lab.studies.s40_daten bericht --ziel ~/tim-research/data/s40
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Iterable, Iterator
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.research_lab.fusion.datenreife import GAP_MS, MAX_GAP_SHARE
from src.research_lab.fusion.historisch import LATENCY_MS, to_ms
from src.research_lab.protocol import HOLDOUT_START_MS
from src.v2_readiness.backfill import parse_official_checksum

Fetcher = Callable[[str], bytes]

MARKETS = {"BTCUSDT": date(2020, 1, 1), "ETHUSDT": date(2020, 1, 1), "SOLUSDT": date(2020, 9, 14)}
FIRST_DAY = date(2020, 1, 1)
LAST_DAY = date(2024, 12, 31)
HOLDOUT_DAY = date(2025, 1, 1)
BAR_MS = 5 * 60_000
DAY_MS = 86_400_000
MIN_OPTION_TRADES = 50       # plan section 4: a Deribit day counts with at least 50 option trades
MIN_VALID_MONTHS = 0.70      # plan section 11
AGG_BASE = "https://data.binance.vision/data/futures/um/daily/aggTrades"
FUNDING_BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
DERIBIT_URL = "https://history.deribit.com/api/v2/public/get_last_trades_by_currency_and_time"
BAR_HEADER = ["open_ms", "open", "high", "low", "close", "buy", "sell", "trades", "last_ts_ms"]
DERIBIT_FIELDS = ("trade_id", "timestamp", "instrument_name", "direction", "amount", "price", "iv", "index_price",
                  "mark_price", "block_trade_id", "combo_id", "combo_trade_id", "liquidation")


class HoldoutRefused(ValueError):
    pass


def _day_ms(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp() * 1000)


def check_day(d: date) -> None:
    if d >= HOLDOUT_DAY or _day_ms(d) >= HOLDOUT_START_MS:
        raise HoldoutRefused(f"{d.isoformat()} lies in the holdout; S40 never loads it")
    if d < FIRST_DAY:
        raise ValueError(f"{d.isoformat()} is before the S40 window")


def days(first: date, last: date) -> list[date]:
    last = min(last, LAST_DAY)
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def months(first: date, last: date) -> list[tuple[int, int]]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (min(last, LAST_DAY).year, min(last, LAST_DAY).month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def http_fetch(url: str, timeout: float = 600.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "tim-research-s40"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def _retry(fetch: Fetcher, url: str, tries: int = 4, wait: float = 5.0) -> bytes:
    for k in range(tries):
        try:
            return fetch(url)
        except Exception:
            if k == tries - 1:
                raise
            time.sleep(wait * 2 ** k)
    raise RuntimeError("unreachable")


# Binance aggTrades -> 5-minute bars ---------------------------------------------------------------------------------
def iter_aggtrades(archive: bytes) -> Iterator[tuple[int, float, float, int]]:
    """(ts_ms, price, qty, side) from a USD-M aggTrades zip; side -1 when the buyer was maker (seller aggressive)."""
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        names = [n for n in bundle.namelist() if n.endswith(".csv")]
        if len(names) != 1:
            raise ValueError("archive must contain exactly one CSV file")
        with bundle.open(names[0]) as raw:
            for row in csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline="")):
                if not row or not row[0].strip().isdigit():
                    continue  # header (archives since 2022) or blank line
                yield to_ms(int(row[5])), float(row[1]), float(row[2]), -1 if row[6].strip().lower() in ("true", "1") else 1


def bars_and_gaps(trades: Iterable[tuple[int, float, float, int]], d: date) -> tuple[list[list[Any]], dict[str, Any]]:
    """5-minute bars of one UTC day plus gap statistics (gap = more than ``GAP_MS`` without a trade, day edges count)."""
    start, end = _day_ms(d), _day_ms(d) + DAY_MS
    bars: dict[int, list[Any]] = {}
    n = outside = 0
    prev = start
    gaps = gap_ms = 0
    for ts, p, q, side in trades:
        if ts >= HOLDOUT_START_MS:
            raise HoldoutRefused("holdout trade inside a pre-2025 archive")
        if not start <= ts < end:
            outside += 1
            continue
        n += 1
        if ts - prev > GAP_MS:
            gaps += 1
            gap_ms += ts - prev
        prev = max(prev, ts)
        k = ts - ts % BAR_MS
        b = bars.get(k)
        if b is None:
            bars[k] = [k, p, p, p, p, q if side == 1 else 0.0, q if side == -1 else 0.0, 1, ts]
        else:
            b[2], b[3], b[4] = max(b[2], p), min(b[3], p), p
            b[5 if side == 1 else 6] += q
            b[7] += 1
            b[8] = max(b[8], ts)
    if end - prev > GAP_MS:
        gaps += 1
        gap_ms += end - prev
    return [bars[k] for k in sorted(bars)], {"trades": n, "outside_day": outside, "gaps": gaps, "gap_ms": gap_ms,
                                             "bars": len(bars)}


def _write_bars(path: Path, rows: list[list[Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(BAR_HEADER)
    w.writerows(rows)
    data = buf.getvalue().encode()
    path.write_bytes(gzip.compress(data, mtime=0))
    return hashlib.sha256(data).hexdigest()


def load_binance_day(root: Path, symbol: str, d: date, fetch: Fetcher = http_fetch) -> dict[str, Any]:
    check_day(d)
    status_path = root / "status" / "binance" / symbol / f"{d.isoformat()}.json"
    if status_path.exists():
        return json.loads(status_path.read_text())
    name = f"{symbol}-aggTrades-{d.isoformat()}.zip"
    url = f"{AGG_BASE}/{symbol}/{name}"
    try:
        expected = parse_official_checksum(_retry(fetch, url + ".CHECKSUM").decode(), expected_filename=name)
        archive = _retry(fetch, url)
    except Exception as exc:  # noqa: BLE001 - a missing day is a finding, not a crash
        st = {"day": d.isoformat(), "symbol": symbol, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        _write_status(status_path, st, final=False)
        return st
    sha = hashlib.sha256(archive).hexdigest()
    if sha != expected:
        st = {"day": d.isoformat(), "symbol": symbol, "ok": False, "error": "checksum mismatch"}
        _write_status(status_path, st, final=False)
        return st
    rows, stats = bars_and_gaps(iter_aggtrades(archive), d)
    bar_sha = _write_bars(root / "bars" / symbol / f"{d.isoformat()}.csv.gz", rows)
    st = {"day": d.isoformat(), "symbol": symbol, "ok": True, "archive_sha256": sha, "bars_sha256": bar_sha, **stats}
    _write_status(status_path, st, final=True)
    return st


def _write_status(path: Path, st: dict[str, Any], *, final: bool) -> None:
    """Final statuses mark a day as done; failed ones go to ``*.failed.json`` so a rerun tries again."""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path if final else path.with_suffix(".failed.json")
    target.write_text(json.dumps(st, sort_keys=True) + "\n")
    if final:
        path.with_suffix(".failed.json").unlink(missing_ok=True)


# Funding -----------------------------------------------------------------------------------------------------------
def load_funding_month(root: Path, symbol: str, y: int, m: int, fetch: Fetcher = http_fetch) -> dict[str, Any]:
    check_day(date(y, m, 1))
    name = f"{symbol}-fundingRate-{y:04d}-{m:02d}.zip"
    target = root / "funding" / symbol / name
    if target.exists():
        return {"file": name, "ok": True, "cached": True}
    url = f"{FUNDING_BASE}/{symbol}/{name}"
    try:
        expected = parse_official_checksum(_retry(fetch, url + ".CHECKSUM").decode(), expected_filename=name)
        data = _retry(fetch, url)
    except Exception as exc:  # noqa: BLE001
        return {"file": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    if hashlib.sha256(data).hexdigest() != expected:
        return {"file": name, "ok": False, "error": "checksum mismatch"}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"file": name, "ok": True}


# Deribit -----------------------------------------------------------------------------------------------------------
def deribit_day(d: date, fetch: Fetcher = http_fetch, pause: float = 0.15, max_pages: int = 5000) -> list[dict]:
    """All BTC option trades of one UTC day, oldest first, deduplicated by ``trade_id``."""
    check_day(d)
    start, end = _day_ms(d), _day_ms(d) + DAY_MS - 1
    seen: set[str] = set()
    out: list[dict] = []
    cursor = start
    for _ in range(max_pages):
        q = urllib.parse.urlencode({"currency": "BTC", "kind": "option", "start_timestamp": cursor,
                                    "end_timestamp": end, "count": 1000, "sorting": "asc"})
        res = json.loads(_retry(fetch, f"{DERIBIT_URL}?{q}"))["result"]
        trades = res.get("trades") or []
        for t in trades:
            ts = to_ms(int(t["timestamp"]))
            if ts >= HOLDOUT_START_MS:
                raise HoldoutRefused("holdout trade in a pre-2025 request")
            tid = str(t.get("trade_id"))
            if tid in seen or not start <= ts <= end:
                continue
            seen.add(tid)
            out.append({k: t.get(k) for k in DERIBIT_FIELDS} | {"recv_ms": ts + LATENCY_MS})
        if not res.get("has_more") or not trades:
            return out
        last = max(int(t["timestamp"]) for t in trades)
        cursor = last if last > cursor else cursor + 1  # equal stamps: repeat that millisecond, ids dedupe
        time.sleep(pause)
    raise RuntimeError(f"{d.isoformat()}: more than {max_pages} pages")


def load_deribit_day(root: Path, d: date, fetch: Fetcher = http_fetch, pause: float = 0.15) -> dict[str, Any]:
    check_day(d)
    status_path = root / "status" / "deribit" / f"{d.isoformat()}.json"
    if status_path.exists():
        return json.loads(status_path.read_text())
    try:
        rows = deribit_day(d, fetch, pause)
    except HoldoutRefused:
        raise
    except Exception as exc:  # noqa: BLE001
        st = {"day": d.isoformat(), "ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        _write_status(status_path, st, final=False)
        return st
    data = "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows).encode()
    path = root / "deribit" / f"{d.isoformat()}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(data, mtime=0))
    blocks = sum(1 for r in rows if r.get("block_trade_id") or r.get("combo_id") or r.get("combo_trade_id"))
    st = {"day": d.isoformat(), "ok": True, "trades": len(rows), "block_or_combo": blocks,
          "no_iv": sum(1 for r in rows if r.get("iv") is None), "sha256": hashlib.sha256(data).hexdigest()}
    _write_status(status_path, st, final=True)
    return st


# Report ------------------------------------------------------------------------------------------------------------
def _statuses(folder: Path) -> list[dict]:
    if not folder.exists():
        return []
    return [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]


def report(root: Path) -> dict[str, Any]:
    """Data maturity per market and month (plan section 4) from the stored day statuses. Reads only."""
    out: dict[str, Any] = {"created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "gap_ms": GAP_MS,
                           "max_gap_share": MAX_GAP_SHARE, "binance": {}, "deribit": {}}
    for symbol, first in MARKETS.items():
        sts = {s["day"]: s for s in _statuses(root / "status" / "binance" / symbol)}
        failed = {p.stem.removesuffix(".failed") for p in (root / "status" / "binance" / symbol).glob("*.failed.json")} \
            if (root / "status" / "binance" / symbol).exists() else set()
        per_month: dict[str, dict[str, Any]] = {}
        for d in days(first, LAST_DAY):
            mk = d.strftime("%Y-%m")
            pm = per_month.setdefault(mk, {"days": 0, "loaded": 0, "missing": 0, "failed": 0, "gap_ms": 0, "trades": 0})
            pm["days"] += 1
            s = sts.get(d.isoformat())
            if s and s.get("ok"):
                pm["loaded"] += 1
                pm["gap_ms"] += s["gap_ms"]
                pm["trades"] += s["trades"]
            elif d.isoformat() in failed:
                pm["failed"] += 1
            else:
                pm["missing"] += 1
        for pm in per_month.values():
            pm["gap_share"] = round(pm["gap_ms"] / (pm["days"] * DAY_MS), 6)
            pm["valid"] = pm["loaded"] == pm["days"] and pm["gap_share"] < MAX_GAP_SHARE
        out["binance"][symbol] = {"months": per_month, **_section_share(per_month)}
    dsts = {s["day"]: s for s in _statuses(root / "status" / "deribit")}
    per_month = {}
    for d in days(FIRST_DAY, LAST_DAY):
        mk = d.strftime("%Y-%m")
        pm = per_month.setdefault(mk, {"days": 0, "valid_days": 0, "missing": 0, "trades": 0, "block_or_combo": 0})
        pm["days"] += 1
        s = dsts.get(d.isoformat())
        if s and s.get("ok"):
            pm["trades"] += s["trades"]
            pm["block_or_combo"] += s["block_or_combo"]
            pm["valid_days"] += s["trades"] >= MIN_OPTION_TRADES
        else:
            pm["missing"] += 1
    for pm in per_month.values():
        pm["valid"] = pm["valid_days"] == pm["days"]
    first_full = next((k for k, v in sorted(per_month.items()) if v["valid"]), None)
    out["deribit"] = {"months": per_month, "first_valid_month": first_full, **_section_share(per_month)}
    return out


def _section_share(per_month: dict[str, dict[str, Any]]) -> dict[str, Any]:
    train = [v for k, v in per_month.items() if k < "2023-01"]
    valid = [v for k, v in per_month.items() if "2023-01" <= k < "2025-01"]
    share = lambda xs: round(sum(v["valid"] for v in xs) / len(xs), 4) if xs else None
    tr, va = share(train), share(valid)
    return {"valid_share_train": tr, "valid_share_validation": va,
            "testable": tr is not None and va is not None and tr >= MIN_VALID_MONTHS and va >= MIN_VALID_MONTHS}


# CLI ---------------------------------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="S40 data loader and maturity report (2020-2024 only)")
    ap.add_argument("phase", choices=["laden", "bericht"])
    ap.add_argument("--ziel", type=Path, required=True)
    ap.add_argument("--teil", choices=["binance", "funding", "deribit", "alle"], default="alle")
    ap.add_argument("--von", type=date.fromisoformat, default=FIRST_DAY)
    ap.add_argument("--bis", type=date.fromisoformat, default=LAST_DAY)
    a = ap.parse_args(argv)
    root = a.ziel.expanduser()
    if a.bis >= HOLDOUT_DAY:
        raise HoldoutRefused("--bis lies in the holdout")
    if a.phase == "bericht":
        rep = report(root)
        (root / "datenreife.json").write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n")
        print(json.dumps({k: v for k, v in rep["binance"].items()} | {"deribit": rep["deribit"]},
                         default=str)[:4000])
        return 0
    log = root / "laden.log"
    root.mkdir(parents=True, exist_ok=True)

    def note(msg: str) -> None:
        with log.open("a") as fh:
            fh.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}\n")

    if a.teil in ("funding", "alle"):
        for symbol, first in MARKETS.items():
            for y, m in months(max(first, a.von), a.bis):
                st = load_funding_month(root, symbol, y, m)
                if not st["ok"]:
                    note(f"funding {st['file']} {st['error']}")
    if a.teil in ("deribit", "alle"):
        for d in days(max(FIRST_DAY, a.von), a.bis):
            st = load_deribit_day(root, d)
            note(f"deribit {d} ok={st['ok']} {st.get('trades', st.get('error'))}")
    if a.teil in ("binance", "alle"):
        for d in days(max(FIRST_DAY, a.von), a.bis):
            for symbol, first in MARKETS.items():
                if d >= first:
                    st = load_binance_day(root, symbol, d)
                    note(f"binance {symbol} {d} ok={st['ok']} {st.get('trades', st.get('error'))}")
    note("fertig")
    return 0


if __name__ == "__main__":
    sys.exit(main())
