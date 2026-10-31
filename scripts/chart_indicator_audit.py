#!/usr/bin/env python3
"""Independent audit of every TIM chart indicator against raw exchange data (read-only).

Two steps, so the raw data can be kept as evidence and the check rerun offline:

  collect: reads the live chart API (/api/chart/live, /api/gamma, /api/liquidation) and the
           raw data behind it straight from the sources: Binance Spot klines and aggTrades
           (REST for today, data.binance.vision daily archives with SHA-256 check for
           finished days), Binance futures open interest and klines, Deribit options book.
  analyze: recomputes each indicator with its own code (nothing from src/ is imported) and
           compares it with what the chart API sends. One row per check: PASS, FAIL or INFO.

  python3 scripts/chart_indicator_audit.py collect --base http://127.0.0.1:8765 --out DIR
  python3 scripts/chart_indicator_audit.py analyze --raw DIR

Nothing here writes to TIM, its database or an exchange account: only public GET requests
and files under DIR. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import sys
import time
import zipfile
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SPOT = "https://api.binance.com"
FAPI = "https://fapi.binance.com"
ARCHIVE = "https://data.binance.vision/data/spot/daily/aggTrades"
DERIBIT = "https://www.deribit.com/api/v2/public"
SYMBOL = "BTCUSDT"
VIEWS = ("5m", "15m", "30m", "1h", "4h", "1d", "1w")
SECONDS = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800}
TICK = 5.0  # finest price level TIM keeps for BTCUSDT
BUCKET = 300  # finest time bucket TIM keeps
BUBBLE_MIN_USD = 100_000.0
UA = {"User-Agent": "TIM-chart-audit/1 (read-only)"}

# --------------------------------------------------------------------------- helpers


def get_json(url: str, params: dict[str, Any] | None = None, timeout: int = 30) -> Any:
    full = url + ("?" + urlencode(params) if params else "")
    for attempt in range(4):
        try:
            with urlopen(Request(full, headers=UA), timeout=timeout) as response:  # noqa: S310 - fixed public hosts
                return json.load(response)
        except Exception:  # noqa: BLE001 - retry public reads a few times
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return None


def get_bytes(url: str, timeout: int = 120) -> bytes:
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers=UA), timeout=timeout) as response:  # noqa: S310
                return response.read()
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    return b""


def save(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, separators=(",", ":")))


def load(path: Path) -> Any:
    return json.loads(path.read_text()) if path.exists() else None


def utc(ts: float) -> datetime:
    return datetime.fromtimestamp(ts, timezone.utc)


def epoch(value: str) -> int:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def day_start(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


def close_to(a: float | None, b: float | None, tol: float) -> bool:
    return a is not None and b is not None and abs(a - b) <= tol


def nice_step(span: float, bins: int) -> float:
    """1-2-2.5-5-10 step (TIM's documented rule for profile rows)."""
    raw = max(span / bins, 1e-9)
    mag = 10 ** math.floor(math.log10(raw))
    for f in (1, 2, 2.5, 5, 10):
        if raw <= f * mag:
            return f * mag
    return 10 * mag


def klines_to_candles(rows: list[list[Any]], now_ms: int) -> list[dict[str, Any]]:
    return [{"t": r[0] // 1000, "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]),
             "volume": float(r[5]), "taker_buy": float(r[9]), "closed": r[6] < now_ms} for r in rows]


# --------------------------------------------------------------------------- trade aggregation (own code)


class TradeBook:
    """Raw aggTrades folded into what the checks need, per UTC day.

    levels: (bucket, tick level) -> [seller-aggressor qty, buyer-aggressor qty]
    orders: (ms, side) -> [qty, notional]  (side 1 = buyer aggressive)
    """

    def __init__(self) -> None:
        self.levels: dict[str, dict[tuple[int, float], list[float]]] = {}
        self.orders: dict[str, dict[tuple[int, int], list[float]]] = {}
        self.count: dict[str, int] = {}
        self.first_id: dict[str, int] = {}
        self.last_id: dict[str, int] = {}

    def add(self, agg_id: int, price: float, qty: float, ms: int, buyer_maker: bool) -> None:
        key = utc(ms / 1000).date().isoformat()
        bucket = (ms // 1000) // BUCKET * BUCKET
        level = math.floor(price / TICK) * TICK
        cell = self.levels.setdefault(key, {}).setdefault((bucket, level), [0.0, 0.0])
        cell[0 if buyer_maker else 1] += qty
        order = self.orders.setdefault(key, {}).setdefault((ms, -1 if buyer_maker else 1), [0.0, 0.0])
        order[0] += qty
        order[1] += price * qty
        self.count[key] = self.count.get(key, 0) + 1
        self.first_id[key] = min(self.first_id.get(key, agg_id), agg_id)
        self.last_id[key] = max(self.last_id.get(key, agg_id), agg_id)

    def dump(self, out: Path) -> None:
        for key in self.levels:
            rows = [[b, lv, round(v[0], 8), round(v[1], 8)] for (b, lv), v in sorted(self.levels[key].items())]
            big = [[ms, round(v[1] / v[0], 8), round(v[0], 8), side, round(v[1], 2)]
                   for (ms, side), v in sorted(self.orders[key].items()) if v[1] >= BUBBLE_MIN_USD]
            ids = [self.first_id[key], self.last_id[key]]
            save(out / f"trades_{key}.json", {"day": key, "rows": rows, "bubbles": big, "count": self.count[key], "ids": ids})


def archive_day(book: TradeBook, day: date, cache: Path) -> dict[str, Any]:
    name = f"{SYMBOL}-aggTrades-{day.isoformat()}.zip"
    path = cache / name
    if not path.exists():
        data = get_bytes(f"{ARCHIVE}/{SYMBOL}/{name}")
        expected = get_bytes(f"{ARCHIVE}/{SYMBOL}/{name}.CHECKSUM").decode().split()[0]
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ValueError(f"checksum mismatch {name}")
        cache.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    count = 0
    with zipfile.ZipFile(path) as archive:
        with archive.open(archive.namelist()[0]) as handle:
            for row in csv.reader(io.TextIOWrapper(handle)):
                if not row or not row[0].isdigit():
                    continue  # header line
                ts = int(row[5])
                ms = ts // 1000 if ts > 10 ** 14 else ts  # spot archives use microseconds since 2025
                book.add(int(row[0]), float(row[1]), float(row[2]), ms, row[6].strip().lower() == "true")
                count += 1
    return {"day": day.isoformat(), "file": name, "trades": count, "sha256_ok": True}


def rest_trades(book: TradeBook, start_ms: int, end_ms: int) -> dict[str, Any]:
    first = get_json(f"{SPOT}/api/v3/aggTrades", {"symbol": SYMBOL, "startTime": start_ms, "endTime": start_ms + 60_000, "limit": 1})
    if not first:
        return {"trades": 0}
    next_id, count, calls, gaps, last = int(first[0]["a"]), 0, 0, 0, None
    while True:
        rows = get_json(f"{SPOT}/api/v3/aggTrades", {"symbol": SYMBOL, "fromId": next_id, "limit": 1000})
        calls += 1
        if not rows:
            break
        done = False
        for r in rows:
            if r["T"] >= end_ms:
                done = True
                break
            if last is not None and r["a"] != last + 1:
                gaps += 1
            last = r["a"]
            book.add(int(r["a"]), float(r["p"]), float(r["q"]), int(r["T"]), bool(r["m"]))
            count += 1
        if done or len(rows) < 1000:
            break
        next_id = rows[-1]["a"] + 1
        time.sleep(0.08)  # aggTrades weight 4: about 3000 weight per minute, half the limit
    return {"trades": count, "calls": calls, "id_gaps": gaps}


# --------------------------------------------------------------------------- collect


def collect(base: str, out: Path, archive_cache: Path, days_back: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"base": base, "started": datetime.now(timezone.utc).isoformat()}
    for tf in VIEWS:
        save(out / f"api_{tf}.json", get_json(f"{base}/api/chart/live", {"symbol": SYMBOL, "tf": tf}, timeout=60))
    save(out / "api_eth_30m.json", get_json(f"{base}/api/chart/live", {"symbol": "ETHUSDT", "tf": "30m"}, timeout=60))
    for name in ("gamma", "liquidation"):
        try:
            save(out / f"api_{name}.json", get_json(f"{base}/api/{name}", timeout=30))
        except Exception as exc:  # noqa: BLE001
            meta[f"api_{name}_error"] = str(exc)
    t0 = datetime.now(timezone.utc)
    meta["api_read_at"] = t0.isoformat()
    now_ms = int(t0.timestamp() * 1000)
    for tf, limit in (("1m", 1000), ("5m", 1000), ("15m", 1000), ("30m", 1000), ("1h", 1000), ("4h", 1000), ("1d", 1000), ("1w", 500), ("1M", 100)):
        save(out / f"kl_{tf}.json", get_json(f"{SPOT}/api/v3/klines", {"symbol": SYMBOL, "interval": tf, "limit": limit}))
    save(out / "kl_eth_30m.json", get_json(f"{SPOT}/api/v3/klines", {"symbol": "ETHUSDT", "interval": "30m", "limit": 1000}))
    # Options and futures sources of the gamma and liquidation layers.
    try:
        save(out / "deribit_book.json", get_json(f"{DERIBIT}/get_book_summary_by_currency", {"currency": "BTC", "kind": "option"}, timeout=60))
        save(out / "deribit_index.json", get_json(f"{DERIBIT}/get_index_price", {"index_name": "btc_usd"}))
    except Exception as exc:  # noqa: BLE001
        meta["deribit_error"] = str(exc)
    try:
        save(out / "fapi_oi.json", get_json(f"{FAPI}/futures/data/openInterestHist", {"symbol": SYMBOL, "period": "30m", "limit": 500}))
        save(out / "fapi_kl.json", get_json(f"{FAPI}/fapi/v1/klines", {"symbol": SYMBOL, "interval": "30m", "limit": 500}))
        save(out / "fapi_oi_now.json", get_json(f"{FAPI}/fapi/v1/openInterest", {"symbol": SYMBOL}))
    except Exception as exc:  # noqa: BLE001
        meta["fapi_error"] = str(exc)
    # Trades: archives for finished days, REST for today up to the API read.
    book = TradeBook()
    today = t0.date()
    meta["archives"] = []
    for offset in range(days_back, 0, -1):
        day = today - timedelta(days=offset)
        try:
            meta["archives"].append(archive_day(book, day, archive_cache))
        except Exception as exc:  # noqa: BLE001 - the newest archive appears some hours after midnight
            meta["archives"].append({"day": day.isoformat(), "error": str(exc)})
    meta["rest_today"] = rest_trades(book, day_start(today) * 1000, now_ms)
    book.dump(out)
    meta["finished"] = datetime.now(timezone.utc).isoformat()
    save(out / "meta.json", meta)
    print(json.dumps({k: v for k, v in meta.items() if k != "archives"}, indent=1))
    print(json.dumps(meta["archives"], indent=1))


# --------------------------------------------------------------------------- analyze

RESULTS: list[dict[str, Any]] = []


def report(indicator: str, check: str, ok: bool | None, detail: str) -> None:
    RESULTS.append({"indicator": indicator, "check": check, "result": "INFO" if ok is None else ("PASS" if ok else "FAIL"), "detail": detail})


def fmt(x: float | None, digits: int = 2) -> str:
    return "–" if x is None else f"{x:,.{digits}f}".replace(",", " ")


class Raw:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.meta = load(folder / "meta.json") or {}
        self.t0 = datetime.fromisoformat(self.meta["api_read_at"])
        self.now_ms = int(self.t0.timestamp() * 1000)
        self.api = {tf: load(folder / f"api_{tf}.json") for tf in VIEWS}
        self.kl = {tf: klines_to_candles(load(folder / f"kl_{tf}.json") or [], self.now_ms) for tf in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1M")}
        self.trades: dict[str, dict[str, Any]] = {}
        for path in sorted(folder.glob("trades_*.json")):
            item = load(path)
            self.trades[item["day"]] = item
        self.archive_days = {a["day"] for a in self.meta.get("archives", []) if a.get("sha256_ok")}

    def drawings(self, tf: str, group: str) -> list[dict[str, Any]]:
        return [d for d in (self.api[tf] or {}).get("drawings", []) if d["group"] == group]

    def closed(self, tf: str) -> list[dict[str, Any]]:
        return [c for c in self.kl[tf] if c["closed"]]


# ---- candles


def check_candles(raw: Raw) -> None:
    for tf in VIEWS:
        api = raw.api[tf]
        ours = {c["t"]: c for c in raw.kl[tf]}
        shown = [c for c in api["candles"] if c["closed"]]
        both = [c for c in shown if c["time"] in ours and ours[c["time"]]["closed"]]
        bad = [c for c in both if any(abs(c[k] - ours[c["time"]][k]) > 1e-9 * max(1.0, abs(c[k])) for k in ("open", "high", "low", "close", "volume"))]
        steps = {b["time"] - a["time"] for a, b in zip(api["candles"], api["candles"][1:])}
        gap = sorted(steps - {SECONDS[tf]}) if tf not in ("1w",) else []
        report("Kerzen", f"{tf}: OHLCV der geschlossenen Kerzen = Binance", not bad and len(both) > 0,
               f"{len(both)} Kerzen verglichen, {len(bad)} abweichend" + (f", Zeitabstände {gap}" if gap else ""))
    eth = load(raw.folder / "api_eth_30m.json")
    ours = {c["t"]: c for c in klines_to_candles(load(raw.folder / "kl_eth_30m.json") or [], raw.now_ms)}
    both = [c for c in eth["candles"] if c["closed"] and c["time"] in ours and ours[c["time"]]["closed"]]
    bad = [c for c in both if any(abs(c[k] - ours[c["time"]][k]) > 1e-9 * max(1.0, c[k]) for k in ("open", "high", "low", "close"))]
    report("Kerzen", "ETHUSDT 30m: OHLC = Binance", not bad and len(both) > 0, f"{len(both)} Kerzen, {len(bad)} abweichend")


# ---- day / week / month highs and lows


def check_extremes(raw: Raw) -> None:
    today = raw.t0.date()
    api = raw.drawings("30m", "day") + raw.drawings("30m", "week") + raw.drawings("30m", "month")

    def find(group: str, prefix: str) -> dict[str, Any] | None:
        return next((d for d in api if d["group"] == group and d["name"].startswith(prefix)), None)

    days = {utc(c["t"]).date(): c for c in raw.kl["1d"]}
    prev = days.get(today - timedelta(days=1))
    for name, key in (("High", "high"), ("Low", "low")):
        d = find("day", name)
        report("Tageslevel", f"1D {name} (Vortag) = Binance-Tageskerze", d is not None and prev is not None and close_to(d["price"], prev[key], 0.005),
               f"Chart {fmt(d['price'] if d else None)} / Binance {fmt(prev[key] if prev else None)}")
        # The line starts at the 30m candle that printed the extreme.
        if d and prev:
            src = [c for c in raw.kl["30m"] if day_start(today - timedelta(days=1)) <= c["t"] < day_start(today) and c[key] == prev[key]]
            report("Tageslevel", f"1D {name}: Linie beginnt an der Kerze des Extrems", bool(src) and d["t1"] == src[0]["t"],
                   f"Linie ab {utc(d['t1']):%d.%m. %H:%M} UTC, Extrem in Kerze {utc(src[0]['t']):%d.%m. %H:%M} UTC" if src else "Kerze nicht gefunden")
    monday = today - timedelta(days=today.weekday())
    week = next((c for c in raw.kl["1w"] if utc(c["t"]).date() == monday - timedelta(days=7)), None)
    for name, key in (("High", "high"), ("Low", "low")):
        d = find("week", name)
        report("Wochenlevel", f"1W {name} (Vorwoche) = Binance-Wochenkerze", d is not None and week is not None and close_to(d["price"], week[key], 0.005),
               f"Chart {fmt(d['price'] if d else None)} / Binance {fmt(week[key] if week else None)}")
    month_start = date(today.year, today.month, 1)
    prev_month = next((c for c in raw.kl["1M"] if utc(c["t"]).date() == (month_start - timedelta(days=1)).replace(day=1)), None)
    for name, key in (("High", "high"), ("Low", "low")):
        d = next((x for x in api if x["group"] == "month" and x["name"] == name and x["tf"] == "1M"), None)
        report("Monatslevel", f"1M {name} (Vormonat) = Binance-Monatskerze", d is not None and prev_month is not None and close_to(d["price"], prev_month[key], 0.005),
               f"Chart {fmt(d['price'] if d else None)} / Binance {fmt(prev_month[key] if prev_month else None)}")
    for group in ("quarter", "year"):
        for d in raw.drawings("30m", group):
            if d["name"] in ("High", "Low"):
                start = d.get("start") or ""
                report("Quartal/Jahr", f"{d['tf']} {d['name']}", None, f"{fmt(d['price'])} ({d.get('note', '')})")


# ---- profiles from trades


def profile(rows: Iterable[tuple[float, float, float]], step: float, first: float) -> dict[str, Any]:
    """Volume per row of width ``step`` from ``first``; POC (lowest of equal rows) and 70 % value area.

    Value area: start at the POC, add the bigger neighbour row (ties: upwards), empty rows inside the range count.
    """
    vol: dict[int, float] = {}
    bid: dict[int, float] = {}
    ask: dict[int, float] = {}
    for level, b, a in rows:
        i = int(math.floor((level - first) / step + 1e-9))
        vol[i] = vol.get(i, 0.0) + b + a
        bid[i] = bid.get(i, 0.0) + b
        ask[i] = ask.get(i, 0.0) + a
    poc = min(vol, key=lambda i: (-vol[i], i))
    total = sum(vol.values())
    lo, hi = min(vol), max(vol)
    up, down, inside = poc + 1, poc - 1, vol[poc]
    while inside < 0.7 * total and (up <= hi or down >= lo):
        u, d = vol.get(up, 0.0), vol.get(down, 0.0)
        if (u >= d and up <= hi) or down < lo:
            inside += u
            up += 1
        else:
            inside += d
            down -= 1
    return {"vol": vol, "bid": bid, "ask": ask, "total": total, "poc": first + poc * step, "poc_mid": first + poc * step + step / 2,
            "vah": first + up * step, "val": first + (down + 1) * step, "share": inside / total if total else 0}


def tim_step(levels: list[float]) -> tuple[float, float]:
    """Row step and first edge by TIM's documented rule (40 rows, whole ticks)."""
    low, high = min(levels), max(levels) + TICK
    step = max(TICK, nice_step(max(high - low, TICK), 40))
    step = math.ceil(step / TICK) * TICK
    return step, math.floor(low / step) * step


def check_volume_profiles(raw: Raw) -> dict[str, dict[str, Any]]:
    api_profiles = {p["day"]: p for p in raw.api["30m"].get("volume_profile", [])}
    ours: dict[str, dict[str, Any]] = {}
    d1 = {utc(c["t"]).date().isoformat(): c for c in raw.kl["1d"]}
    for day, p in sorted(api_profiles.items()):
        trades = raw.trades.get(day)
        kline = d1.get(day)
        # 1) completeness: TIM's stored volume against the Binance day candle (independent of our trades)
        if kline and p.get("complete") and not p.get("running"):
            diff = (p["total"] - kline["volume"]) / kline["volume"] * 100
            report("Volume Profile", f"{day}: Gesamtvolumen TIM-Trades = Binance-Tageskerze", abs(diff) < 0.01,
                   f"TIM {fmt(p['total'], 3)} BTC / Binance {fmt(kline['volume'], 3)} BTC ({diff:+.4f} %)")
            delta_binance = 2 * kline["taker_buy"] - kline["volume"]
            report("Volume Profile", f"{day}: Delta (Käufer − Verkäufer) = Binance-Tageskerze", abs(p["delta"] - delta_binance) <= max(0.5, 1e-4 * kline["volume"]),
                   f"TIM {p['delta']:+,.2f} / Binance {delta_binance:+,.2f} BTC")
        if not trades or p.get("running"):
            continue
        # 2) every row against our own aggregation of the Binance archive at TIM's step
        step = float(p["step"])
        first = min(r["price"] for r in p["rows"])
        report("Volume Profile", f"{day}: Zeilenbreite ist ganzzahliges Vielfaches von 5 USDT", abs(step / TICK - round(step / TICK)) < 1e-9, f"Schritt {step}")
        ours_p = profile(((lv, b, a) for _, lv, b, a in trades["rows"]), step, math.floor(first / step) * step)
        exp_step, _ = tim_step([lv for _, lv, _, _ in trades["rows"]])
        report("Volume Profile", f"{day}: Zeilenbreite nach Regel (≈40 Zeilen)", abs(exp_step - step) < 1e-9, f"TIM {step} / nachgerechnet {exp_step}")
        worst = 0.0
        for r in p["rows"]:
            i = int(round((r["price"] - math.floor(first / step) * step) / step))
            mine = ours_p["vol"].get(i, 0.0)
            worst = max(worst, abs(mine - r["volume"]))
        report("Volume Profile", f"{day}: Volumen je Zeile = Binance-Archiv (eigene Summe)", worst <= 0.01 + 1e-5 * p["max_volume"],
               f"{len(p['rows'])} Zeilen, größte Abweichung {worst:.4f} BTC")
        for key in ("poc", "vah", "val"):
            report("Volume Profile", f"{day}: {key.upper()} = eigene Rechnung", close_to(p[key], ours_p[key], 1e-6), f"TIM {fmt(p[key])} / eigen {fmt(ours_p[key])}")
        ours[day] = {**ours_p, "step": step}
    return ours


def check_trade_levels(raw: Raw, ours: dict[str, dict[str, Any]]) -> None:
    today = raw.t0.date()
    yesterday = (today - timedelta(days=1)).isoformat()
    day_lines = {d["name"]: d for d in raw.drawings("30m", "day")}
    y = ours.get(yesterday)
    if y:
        for name, key in (("VAH", "vah"), ("POC", "poc_mid"), ("VAL", "val")):
            d = day_lines.get(name)
            report("Tageslevel", f"1D {name} Vortag aus echten Trades (Binance-Archiv)", d is not None and close_to(d["price"], y[key], 1e-6) and d.get("source") == "trades",
                   f"Chart {fmt(d['price'] if d else None)} / eigen {fmt(y[key])}" + ("" if d and d.get("source") == "trades" else " (Linie nicht aus Trades)"))
    else:
        report("Tageslevel", "1D VAH/POC/VAL Vortag", None, "Archiv des Vortags noch nicht da: nicht nachgerechnet")
    # previous week from the archives, TIM's row rule
    monday = today - timedelta(days=today.weekday())
    keys = [(monday - timedelta(days=7 - i)).isoformat() for i in range(7)]
    week_lines = {d["name"]: d for d in raw.drawings("30m", "week")}
    if all(k in raw.trades and k in raw.archive_days for k in keys):
        rows = [(lv, b, a) for k in keys for _, lv, b, a in raw.trades[k]["rows"]]
        step, first = tim_step([r[0] for r in rows])
        w = profile(rows, step, first)
        for name, key in (("VAH", "vah"), ("POC", "poc_mid"), ("VAL", "val")):
            d = week_lines.get(name)
            report("Wochenlevel", f"1W {name} Vorwoche aus echten Trades (7 Archive)", d is not None and close_to(d["price"], w[key], 1e-6),
                   f"Chart {fmt(d['price'] if d else None)} / eigen {fmt(w[key])} (Schritt {step})")
    else:
        report("Wochenlevel", "1W VAH/POC/VAL Vorwoche", None, "nicht alle 7 Archive vorhanden")
    # running day and week POC
    running = {(d["tf"], d["name"]): d for d in raw.drawings("30m", "running")}
    today_key = today.isoformat()
    if today_key in raw.trades:
        cutoff = epoch(raw.api["30m"].get("trades_updated_at") or raw.t0.isoformat()) // BUCKET * BUCKET - BUCKET
        rows = [(lv, b, a) for t, lv, b, a in raw.trades[today_key]["rows"] if t < cutoff]
        step, first = tim_step([r[0] for r in rows])
        r = profile(rows, step, first)
        d = running.get(("1D", "POC lfd."))
        report("Laufende POCs", "1D POC lfd. (heute) aus echten Trades", d is not None and abs(d["price"] - r["poc_mid"]) <= step,
               f"Chart {fmt(d['price'] if d else None)} / eigen {fmt(r['poc_mid'])} (Schritt {step}; heute läuft noch, 1 Zeile Toleranz)")
        wk = [(monday + timedelta(days=i)).isoformat() for i in range((today - monday).days + 1)]
        if all(k in raw.trades for k in wk):
            rows = [(lv, b, a) for k in wk for t, lv, b, a in raw.trades[k]["rows"] if t < cutoff]
            step, first = tim_step([x[0] for x in rows])
            r = profile(rows, step, first)
            d = running.get(("1W", "POC lfd."))
            report("Laufende POCs", "1W POC lfd. (diese Woche) aus echten Trades", d is not None and abs(d["price"] - r["poc_mid"]) <= step,
                   f"Chart {fmt(d['price'] if d else None)} / eigen {fmt(r['poc_mid'])} (Schritt {step})")


def check_naked(raw: Raw, ours: dict[str, dict[str, Any]], tpo: dict[str, dict[str, Any]]) -> None:
    today = raw.t0.date()
    yesterday = (today - timedelta(days=1)).isoformat()
    naked = raw.drawings("30m", "naked")
    shown_v = {d["start"][:10]: d for d in naked if d["name"].startswith("nPOC") and d.get("source") == "trades"}
    shown_t = {d["start"][:10]: d for d in naked if d["name"].startswith("tPOC")}
    traded: dict[str, set[float]] = {k: {lv for _, lv, _, _ in v["rows"]} for k, v in raw.trades.items()}
    cutoff_day = today.isoformat()
    expected_v = {}
    for day, p in sorted(ours.items()):
        if day in (yesterday, cutoff_day):
            continue
        later = set().union(*(traded[k] for k in traded if k > day))
        row = {p["poc"] + i * TICK for i in range(int(round(p["step"] / TICK)))}
        if not row & later:
            expected_v[day] = p["poc_mid"]
    for day in sorted(set(expected_v) | set(shown_v)):
        d = shown_v.get(day)
        ok = day in expected_v and d is not None and close_to(d["price"], expected_v[day], 1e-6)
        report("naked POC", f"nPOC {day}: unberührt laut Binance-Trades", ok,
               f"Chart {fmt(d['price'] if d else None)} / eigen {fmt(expected_v.get(day))}" + ("" if day in expected_v else " (eigen: berührt)") + ("" if d else " (fehlt im Chart)"))
    covered = sorted(k for k in ours if k not in (yesterday, cutoff_day))
    report("naked POC", "vPOC-Prüfung deckt Tage ab", None, f"{len(covered)} Tage mit Archiv: {covered[0] if covered else '–'} bis {covered[-1] if covered else '–'}")
    # tPOC: from our TPO profiles, touched by any later closed 30m Binance candle inside the row
    closed30 = raw.closed("30m")
    for day, p in sorted(tpo.items()):
        if p["running"] or day == yesterday or p["periods"] < 44:
            continue
        end = day_start(date.fromisoformat(day)) + 86400
        low, high = p["poc"], p["poc"] + p["step"]
        touched = any(c["t"] >= end and c["low"] < high and c["high"] >= low for c in closed30)
        d = shown_t.get(day)
        ok = (not touched and d is not None and close_to(d["price"], low + p["step"] / 2, 1e-6)) or (touched and d is None)
        report("naked POC", f"tPOC {day}: {'unberührt' if not touched else 'berührt'} laut Binance-30m", ok,
               f"Chart {'zeigt ' + fmt(d['price']) if d else 'zeigt keinen'} / eigen {fmt(low + p['step'] / 2) if not touched else 'berührt'}")
    if "2026-10-22" in ours:
        p = ours["2026-10-22"]
        report("naked POC", "Fall Beirat 29.10.: vPOC 22.10. (Broncx 82 800)", None,
               f"eigen POC-Mitte {fmt(p['poc_mid'])}, im Chart {'ja' if '2026-10-22' in shown_v else 'nein'}" + ("" if "2026-10-22" in expected_v else " (inzwischen berührt)"))


# ---- TPO


TPO_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuv"


def own_tpo(candles: list[dict[str, Any]], day: date, step: float, two_rows: bool = False) -> dict[str, Any] | None:
    start = day_start(day)
    periods = {}
    for c in candles:
        if start <= c["t"] < start + 86400 and c["closed"]:
            periods[(c["t"] - start) // 1800] = c
    if len(periods) < 2:
        return None
    low = min(c["low"] for c in periods.values())
    first = math.floor(low / step) * step
    letters: dict[int, str] = {}
    for slot in sorted(periods):
        c = periods[slot]
        for i in range(int((c["low"] - first) // step), int((c["high"] - first) // step) + 1):
            letters[i] = letters.get(i, "") + TPO_LETTERS[slot]
    total = sum(len(v) for v in letters.values())
    mid = (max(letters) + min(letters)) / 2
    poc = max(sorted(letters), key=lambda i: (len(letters[i]), -abs(i - mid)))
    up, down, inside = poc + 1, poc - 1, len(letters[poc])
    while inside < total * 0.7 and (up in letters or down in letters):
        if two_rows:  # CBOT convention: compare the next two rows on each side
            u = len(letters.get(up, "")) + len(letters.get(up + 1, ""))
            d = len(letters.get(down, "")) + len(letters.get(down - 1, ""))
            if u >= d and up in letters:
                inside += u
                up += 2
            else:
                inside += d
                down -= 2
            continue
        u, d = len(letters.get(up, "")), len(letters.get(down, ""))
        if u >= d and up in letters:
            inside += u
            up += 1
        else:
            inside += d
            down -= 1
    edge = {TPO_LETTERS[min(periods)], TPO_LETTERS[max(periods)]}
    singles = {round(first + i * step, 8) for i in letters if len(letters[i]) == 1 and letters[i] not in edge and min(letters) < i < max(letters)}
    return {"letters": {round(first + i * step, 8): v for i, v in letters.items()}, "poc": first + poc * step, "vah": first + up * step,
            "val": first + (down + 1) * step, "singles": singles, "periods": len(periods), "step": step,
            "high": max(c["high"] for c in periods.values()), "low": low, "running": day == date.today()}


def check_tpo(raw: Raw) -> dict[str, dict[str, Any]]:
    result = {}
    today = raw.t0.date()
    for p in raw.api["30m"].get("tpo", []):
        day = date.fromisoformat(p["day"])
        if p["running"]:
            continue
        mine = own_tpo(raw.kl["30m"], day, float(p["step"]))
        if mine is None:
            continue
        mine["running"] = day == today
        span = max(mine["high"] - mine["low"], mine["high"] * 0.0005)
        report("TPO", f"{p['day']}: Zeilenbreite nach Regel (≈40 Zeilen)", abs(nice_step(span, 40) - p["step"]) < 1e-9, f"TIM {p['step']} / nachgerechnet {nice_step(span, 40)}")
        api_letters = {round(r["price"], 8): r["letters"] for r in p["rows"]}
        same = api_letters == mine["letters"]
        diff = sorted(set(api_letters.items()) ^ set(mine["letters"].items()))[:3]
        report("TPO", f"{p['day']}: Buchstaben je Zeile = Binance-30m", same, f"{len(api_letters)} Zeilen, {p['periods']} Perioden" + ("" if same else f", Abweichung {diff}"))
        for key in ("poc", "vah", "val"):
            report("TPO", f"{p['day']}: {key.upper()} = eigene Rechnung", close_to(p[key], mine[key], 1e-6), f"TIM {fmt(p[key])} / eigen {fmt(mine[key])}")
        singles = {round(r["price"], 8) for r in p["rows"] if r["single"]}
        report("TPO", f"{p['day']}: Single Prints = eigene Rechnung", singles == mine["singles"], f"{len(singles)} Single Prints")
        cbot = own_tpo(raw.kl["30m"], day, float(p["step"]), two_rows=True)
        if cbot and (cbot["vah"] != mine["vah"] or cbot["val"] != mine["val"]):
            report("TPO", f"{p['day']}: Value Area nach CBOT-Regel (2 Zeilen je Schritt)", None,
                   f"TIM {fmt(p['val'])}–{fmt(p['vah'])} / CBOT {fmt(cbot['val'])}–{fmt(cbot['vah'])}")
        result[p["day"]] = mine
    # days the naked tPOC check needs beyond the six drawn profiles
    for offset in range(2, 15):
        day = today - timedelta(days=offset)
        if day.isoformat() in result:
            continue
        candles = [c for c in raw.kl["30m"] if day_start(day) <= c["t"] < day_start(day) + 86400]
        if len(candles) < 2:
            continue
        span = max(max(c["high"] for c in candles) - min(c["low"] for c in candles), max(c["high"] for c in candles) * 0.0005)
        mine = own_tpo(raw.kl["30m"], day, nice_step(span, 40))
        if mine:
            mine["running"] = False
            result[day.isoformat()] = mine
    return result


# ---- sessions and IB


def check_sessions(raw: Raw) -> None:
    sessions = {d["name"]: d for d in raw.drawings("30m", "session")}
    closed = raw.closed("30m")
    today = raw.t0.date()
    for name, (h0, m0), (h1, m1), zone in (("Asia", (9, 0), (15, 0), "Asia/Tokyo"), ("London", (8, 0), (16, 30), "Europe/London"),
                                            ("New York", (9, 30), (16, 0), "America/New_York")):
        for offset in (0, 1):
            day = today - timedelta(days=offset)
            tz = ZoneInfo(zone)
            begin = datetime(day.year, day.month, day.day, h0, m0, tzinfo=tz).astimezone(timezone.utc)
            end = datetime(day.year, day.month, day.day, h1, m1, tzinfo=tz).astimezone(timezone.utc)
            inside = [c for c in closed if begin.timestamp() <= c["t"] < end.timestamp()]
            if begin > raw.t0 or not inside:
                continue
            for side, key, fn in (("High", "high", max), ("Low", "low", min)):
                d = sessions.get(f"{name} {side}")
                value = fn(c[key] for c in inside)
                report("Sessions", f"{name} {side} ({begin:%d.%m. %H:%M}–{end:%H:%M} UTC) = Binance-30m", d is not None and close_to(d["price"], value, 0.005),
                       f"Chart {fmt(d['price'] if d else None)} / Binance {fmt(value)}")
            break
    ib = {d["name"]: d for d in raw.drawings("30m", "ib")}
    start = day_start(today)
    inside = [c for c in closed if start <= c["t"] < start + 5400]
    if inside:
        for side, key, fn in (("High", "high", max), ("Low", "low", min)):
            d = ib.get(f"IB {side}")
            value = fn(c[key] for c in inside)
            report("Initial Balance", f"IB {side} (00:00–01:30 UTC) = Binance-30m", d is not None and close_to(d["price"], value, 0.005),
                   f"Chart {fmt(d['price'] if d else None)} / Binance {fmt(value)}")


# ---- BOS / MSS and trend lines


def is_swing(candles: list[dict[str, Any]], i: int, kind: str, width: int, equal_left: bool) -> bool:
    if i - width < 0 or i + width >= len(candles):
        return False
    key = "high" if kind == "HIGH" else "low"
    v = candles[i][key]
    left, right = candles[i - width:i], candles[i + 1:i + width + 1]
    if kind == "HIGH":
        return all((v >= c[key]) if equal_left else (v > c[key]) for c in left) and all(v > c[key] for c in right)
    return all((v <= c[key]) if equal_left else (v < c[key]) for c in left) and all(v < c[key] for c in right)


def check_structure(raw: Raw) -> None:
    for tf in ("5m", "15m", "30m", "1h", "4h", "1d"):
        closed = [c for c in raw.kl[tf] if c["closed"]]
        index = {c["t"]: i for i, c in enumerate(closed)}
        events = [d for d in raw.drawings(tf, "structure") if not d.get("open")]
        problems = []
        for e in events:
            s, b = index.get(epoch(e["start"])), index.get(epoch(e["end"]))
            if s is None or b is None:
                problems.append(f"{e['name']} Zeit nicht in Binance-Kerzen")
                continue
            up = e["direction"] == "UP"
            close = closed[b]["close"]
            if not (close > e["price"] if up else close < e["price"]):
                problems.append(f"{e['name']} {utc(closed[b]['t']):%d.%m. %H:%M}: Schluss {close} nicht jenseits {e['price']}")
            # the break is the first close beyond the level after the swing was confirmed (width 3)
            first = next((j for j in range(s + 1, b + 1) if (closed[j]["close"] > e["price"] if up else closed[j]["close"] < e["price"])), None)
            if e["name"].startswith("BOS") and first != b:
                problems.append(f"{e['name']} früherer Schluss jenseits des Levels bei {utc(closed[first]['t']):%d.%m. %H:%M}")
            if e["name"].startswith("BOS"):
                key = "high" if up else "low"
                if closed[s][key] != e["price"] or not is_swing(closed, s, "HIGH" if up else "LOW", 3, True):
                    problems.append(f"{e['name']} Level {e['price']} ist kein 3er-Swing-{'Hoch' if up else 'Tief'}")
            else:  # MSS: break of the protected level, which is a candle extreme
                key = "low" if not up else "high"
                if closed[s][key] != e["price"]:
                    problems.append(f"{e['name']} Level {e['price']} ist nicht das {'Tief' if not up else 'Hoch'} der Kerze {utc(closed[s]['t']):%d.%m. %H:%M}")
        report("BOS / MSS", f"{tf}: {len(events)} Brüche: Schluss jenseits, erster Schluss, Level = Swing", not problems and bool(events) or (not events and None),
               "; ".join(problems[:3]) if problems else f"{len(events)} Ereignisse geprüft")
        for d in raw.drawings(tf, "structure"):
            if d.get("open"):
                i = index.get(epoch(d["start"]))
                key = "low" if ("Low" in d["name"] or (d["name"].startswith("BOS") and d["direction"] == "DOWN")) else "high"
                ok = i is not None and closed[i][key] == d["price"]
                after = closed[i + 1:] if i is not None else []
                if d["name"].startswith("Strong"):
                    broken = any((c["close"] < d["price"]) if key == "low" else (c["close"] > d["price"]) for c in after)
                    ok = ok and not broken
                report("BOS / MSS", f"{tf}: offenes Level {d['name']} {fmt(d['price'])}", ok,
                       "Level ist Kerzenextrem und noch nicht per Schluss gebrochen" if ok else "Level passt nicht zur Kerze oder ist schon gebrochen")


def check_trend(raw: Raw) -> None:
    for tf in ("15m", "30m", "1h", "4h", "1d"):
        closed = [c for c in raw.kl[tf] if c["closed"]]
        index = {c["t"]: i for i, c in enumerate(closed)}
        for d in raw.drawings(tf, "trend"):
            kind = "HIGH" if "Hochs" in d["name"] else "LOW"
            key = kind.lower()
            a, b = index.get(epoch(d["start"])), index.get(epoch(d["anchor_time"]))
            problems = []
            if a is None or b is None:
                report("Trendlinien", f"{tf}: {d['name']}", False, "Ankerkerzen nicht gefunden")
                continue
            for i in (a, b):
                if not is_swing(closed, i, kind, 5, False):
                    problems.append(f"Anker {utc(closed[i]['t']):%d.%m. %H:%M} kein 5er-Swing")
            if closed[a][key] != d["start_price"] or closed[b][key] != d["anchor_price"]:
                problems.append("Ankerpreise ≠ Kerzenextreme")
            later = [i for i in range(b + 1, len(closed)) if is_swing(closed, i, kind, 5, False) and i + 5 < len(closed)]
            if later:
                problems.append(f"neuerer Swing bei {utc(closed[later[-1]]['t']):%d.%m. %H:%M} nicht benutzt")
            slope = (d["anchor_price"] - d["start_price"]) / (b - a)
            brk = next((i for i in range(b + 1, len(closed)) if (closed[i]["close"] > d["anchor_price"] + slope * (i - b) if kind == "HIGH" else closed[i]["close"] < d["anchor_price"] + slope * (i - b))), None)
            if bool(d.get("broken")) != (brk is not None):
                problems.append("Bruch-Status falsch")
            report("Trendlinien", f"{tf}: {d['name']}", not problems, "; ".join(problems) if problems else "Anker sind die letzten zwei 5er-Swings, Bruch per Schluss stimmt")


# ---- VWAP


def own_vwap(candles: list[dict[str, Any]]) -> tuple[float, float]:
    vol = sum(c["volume"] for c in candles)
    tp = [((c["high"] + c["low"] + c["close"]) / 3, c["volume"]) for c in candles]
    value = sum(p * v for p, v in tp) / vol
    sigma = math.sqrt(max(sum(v * (p - value) ** 2 for p, v in tp) / vol, 0.0))
    return value, sigma


def check_vwap(raw: Raw) -> None:
    today = raw.t0.date()
    anchors = {"1W": today - timedelta(days=today.weekday()), "1M": today.replace(day=1),
               "1Q": today.replace(month=(today.month - 1) // 3 * 3 + 1, day=1), "1Y": today.replace(month=1, day=1)}
    # Current values (label price on views where the anchor is out of sight) come from the TIM runtime 1h candles.
    lines = {d["tf"]: d for d in raw.drawings("1w", "vwap")}
    hours = raw.closed("1h")
    days = raw.closed("1d")
    trade_rows = raw.trades
    for tf, anchor in anchors.items():
        d = lines.get(tf)
        if d is None:
            report("VWAP", f"{tf} VWAP ab {anchor:%d.%m.}", None, "nicht im Chart (Quartal = Monat bei gleichem Anker)" if tf == "1Q" else "nicht im Chart")
            continue
        options = {}
        for label, source in (("1h", hours), ("1d", days)):
            rows = [c for c in source if c["t"] >= day_start(anchor)]
            if rows and rows[0]["t"] <= day_start(anchor) and not (tf == "1Y" and label == "1h"):
                options[label] = own_vwap(rows)[0]
        used = (d.get("note") or "").split("aus ")[-1].split("-")[0]
        value = options.get(used, options.get("1h", options.get("1d")))
        report("VWAP", f"{tf} VWAP ab {anchor:%d.%m.}: Wert = eigene Rechnung (typ. Preis, Binance-{used}-Kerzen)", value is not None and abs(d["price"] - value) <= 1.0,
               f"Chart {fmt(d['price'])} / eigen {fmt(value)}" + (f"; mit 1h-Kerzen wäre es {fmt(options['1h'])}" if used == "1d" and "1h" in options else ""))
        # How far the candle estimate is from the exact trade VWAP (all trades since the anchor, when we have them)
        keys = [(anchor + timedelta(days=i)).isoformat() for i in range((today - anchor).days + 1)]
        if all(k in trade_rows for k in keys):
            q = n = 0.0
            for k in keys:
                for _, lv, b, a in trade_rows[k]["rows"]:
                    q += (lv + TICK / 2) * (b + a)
                    n += b + a
            exact = q / n
            report("VWAP", f"{tf} VWAP: Abstand zur exakten Trade-VWAP", None, f"Kerzen-Schätzung {fmt(value)} / Trades {fmt(exact)} ({(value - exact) / exact * 100:+.3f} %)")
    # Weekly bands on a view where the week starts in sight (30m): curve against our own running VWAP
    for tf in ("30m", "1h"):
        curves = {d["name"]: d for d in raw.drawings(tf, "vwap") + raw.drawings(tf, "vwap_bands") if d["tf"] == "1W" and d.get("curve")}
        if "VWAP" not in curves:
            continue
        candles = [c for c in raw.kl[tf] if c["t"] >= day_start(anchors["1W"])]
        w = q = s = 0.0
        own = {}
        for c in candles:
            tp = (c["high"] + c["low"] + c["close"]) / 3
            q += tp * c["volume"]
            s += tp * tp * c["volume"]
            w += c["volume"]
            if w > 0:
                v = q / w
                own[c["t"]] = (v, math.sqrt(max(s / w - v * v, 0.0)))
        worst = {}
        for name, factor in (("VWAP", 0), ("VWAP +1σ", 1), ("VWAP +2σ", 2), ("VWAP −1σ", -1), ("VWAP −2σ", -2)):
            d = curves.get(name)
            if not d:
                report("VWAP-Bänder", f"{tf}: {name} vorhanden", False, "fehlt")
                continue
            # the open candle moves with every trade: compare the closed ones
            pts = [(t, v) for t, v in d["curve"] if t in own and any(c["t"] == t and c["closed"] for c in candles)]
            worst[name] = max(abs(v - (own[t][0] + factor * own[t][1])) for t, v in pts) if pts else None
            report("VWAP-Bänder" if factor else "VWAP", f"{tf}: Linie {name} Woche je Kerze = eigene Rechnung", worst[name] is not None and worst[name] <= 0.5,
                   f"{len(pts)} Punkte, größte Abweichung {fmt(worst[name])} USDT")


# ---- Fibonacci


def check_fib(raw: Raw) -> None:
    for tf in ("15m", "30m", "1h", "4h", "1d"):
        fib = raw.api[tf].get("fib")
        closed = raw.closed(tf)
        if not fib:
            report("Fibonacci", f"{tf}", None, "keine Fib im Chart")
            continue
        index = {c["t"]: i for i, c in enumerate(closed)}
        problems = []
        tail = closed[-101:]
        atr = sum(max(c["high"], p["close"]) - min(c["low"], p["close"]) for p, c in zip(tail, tail[1:])) / (len(tail) - 1)
        # the API reads its candles a moment earlier: the newest closed candle may differ by one
        if abs(fib["threshold"] - 3 * atr) > 0.02 * fib["threshold"]:
            problems.append(f"Schwelle {fib['threshold']:.2f} ≠ 3×ATR {3 * atr:.2f}")
        a, b = index.get(fib["start"]), index.get(fib["end"])
        if a is None or b is None or a >= b:
            problems.append("Anker nicht in Binance-Kerzen")
        else:
            up = fib["direction"] == "UP"
            sk, ek = ("low", "high") if up else ("high", "low")
            if closed[a][sk] != fib["start_price"] or closed[b][ek] != fib["end_price"]:
                problems.append("Ankerpreise ≠ Dochte")
            leg = closed[a:b + 1]
            if up and (min(c["low"] for c in leg) < fib["start_price"] or max(c["high"] for c in leg) > fib["end_price"]):
                problems.append("Anker sind nicht Tief/Hoch des Schenkels")
            if not up and (max(c["high"] for c in leg) > fib["start_price"] or min(c["low"] for c in leg) < fib["end_price"]):
                problems.append("Anker sind nicht Hoch/Tief des Schenkels")
            if abs(fib["end_price"] - fib["start_price"]) < fib["threshold"]:
                problems.append("Schenkel kleiner als Schwelle")
            later = closed[b + 1:]
            lo, hi = sorted((fib["start_price"], fib["end_price"]))
            if later and (min(c["low"] for c in later) < lo or max(c["high"] for c in later) > hi):
                problems.append("spätere Kerze außerhalb des Schenkels (Fib veraltet)")
        span = fib["end_price"] - fib["start_price"]
        for lv in fib["levels"]:
            if abs(lv["price"] - (fib["end_price"] - span * lv["ratio"])) > 1e-6:
                problems.append(f"Level {lv['ratio']} falsch")
        report("Fibonacci", f"{tf}: Anker, Schwelle 3×ATR(100), Level-Arithmetik", not problems,
               "; ".join(problems) if problems else f"{fib['direction']} {fmt(fib['start_price'])} → {fmt(fib['end_price'])}, 0,618 = {fmt(next(l['price'] for l in fib['levels'] if l['ratio'] == 0.618))}")


# ---- footprint and bubbles


def check_footprint(raw: Raw) -> None:
    today = raw.t0.date().isoformat()
    for tf in ("5m", "15m", "30m", "1h", "4h"):
        fp = raw.api[tf].get("footprint") or {}
        bars = fp.get("bars") or []
        kl = {c["t"]: c for c in raw.kl[tf] if c["closed"]}
        if not bars:
            report("Footprint", f"{tf}", None, fp.get("note") or "keine Footprint-Kerzen")
            continue
        # 1) every bar against the Binance candle: volume and delta (taker buy) - independent of our trades
        worst_v = worst_d = 0.0
        n = 0
        for b in bars:
            c = kl.get(b["time"])
            if not c:
                continue
            n += 1
            worst_v = max(worst_v, abs(b["total"] - c["volume"]))
            worst_d = max(worst_d, abs(b["delta"] - (2 * c["taker_buy"] - c["volume"])))
        report("Footprint", f"{tf}: Volumen und Delta je Kerze = Binance-Kerze", n > 0 and worst_v <= 0.01 and worst_d <= 0.02,
               f"{n} geschlossene Kerzen, größte Abweichung Volumen {worst_v:.4f} BTC, Delta {worst_d:.4f} BTC")
        # 2) cells, POC, imbalances, stacks, unfinished auctions from our own trades (only bars fully in our data)
        step = float(fp["step"])
        cells: dict[int, dict[float, list[float]]] = {}
        ticks: dict[int, dict[float, list[float]]] = {}
        sec = SECONDS[tf]
        first_bar = bars[0]["time"]
        for key, item in raw.trades.items():
            for t, lv, bid, ask in item["rows"]:
                if t < first_bar:
                    continue
                bt = first_bar + (t - first_bar) // sec * sec
                cell = cells.setdefault(bt, {}).setdefault(round(math.floor(lv / step) * step, 8), [0.0, 0.0])
                cell[0] += bid
                cell[1] += ask
                tk = ticks.setdefault(bt, {}).setdefault(lv, [0.0, 0.0])
                tk[0] += bid
                tk[1] += ask
        checked = mism = imb_bad = stack_bad = auction_bad = poc_bad = gaps = rows_total = 0
        example = ""
        updated = epoch(raw.api[tf].get("trades_updated_at") or raw.t0.isoformat())
        for b in bars:
            if b["time"] not in kl or b["time"] + sec > updated - 60 or b["time"] not in cells:
                continue
            day = utc(b["time"]).date().isoformat()
            if day not in raw.archive_days and day != today:
                continue
            mine = cells[b["time"]]
            api = {round(p, 8): (bid, ask) for p, bid, ask in b["levels"]}
            checked += 1
            bad = [p for p in set(mine) | set(api) if abs(mine.get(p, [0, 0])[0] - api.get(p, (0, 0))[0]) > 1e-3 or abs(mine.get(p, [0, 0])[1] - api.get(p, (0, 0))[1]) > 1e-3]
            if bad:
                mism += 1
                example = example or f"{utc(b['time']):%d.%m. %H:%M} Zeile {bad[0]}"
            prices = sorted(mine)
            poc = max(prices, key=lambda p: (mine[p][0] + mine[p][1], -p))
            poc_bad += poc != b["poc"]
            imb, ties = [], set()
            for i, p in enumerate(prices):
                bid, ask = mine[p]
                # Rule (docstring F1): the diagonal row one step away; an empty row there counts as zero.
                below = mine.get(round(p - step, 8), [0.0, 0.0])
                above = mine.get(round(p + step, 8), [0.0, 0.0])
                if i > 0 and ask > 0:
                    other = 4 * below[0]
                    if ask >= other:
                        imb.append([p, "ask"])
                    if abs(ask - other) <= 1e-9 * max(ask, 1e-12):
                        ties.add((p, "ask"))  # exactly 400 %: float rounding decides, not a finding
                    gaps += round((p - prices[i - 1]) / step) > 1
                if i + 1 < len(prices) and bid > 0:
                    other = 4 * above[1]
                    if bid >= other:
                        imb.append([p, "bid"])
                    if abs(bid - other) <= 1e-9 * max(bid, 1e-12):
                        ties.add((p, "bid"))
                rows_total += 1
            imb_bad += bool((set(map(tuple, imb)) ^ set(map(tuple, b["imbalances"]))) - ties)
            stacks = []
            for side in ("ask", "bid"):
                marked = sorted(p for p, s in imb if s == side)
                run = []
                for p in marked + [math.inf]:
                    if run and abs(p - run[-1] - step) < 1e-6:
                        run.append(p)
                        continue
                    if len(run) >= 3:
                        stacks.append((run[0], run[-1], side))
                    run = [p]
            stack_bad += sorted(stacks) != sorted(map(tuple, b["stacked"]))
            tk = ticks[b["time"]]
            top, bottom = tk[max(tk)], tk[min(tk)]
            auction_bad += (min(top) > 0) != b["unfinished_high"] or (min(bottom) > 0) != b["unfinished_low"]
        report("Footprint", f"{tf}: Bid × Ask je Zeile = Binance-aggTrades (eigene Summe)", checked > 0 and mism == 0,
               f"{checked} Kerzen mit eigenen Trades verglichen, {mism} abweichend" + (f" (z. B. {example})" if example else ""))
        report("Footprint", f"{tf}: Zeilen mit leerer Nachbarzeile (Randfall Imbalance)", None,
               f"{gaps} von {rows_total} Zeilen haben eine leere Zeile direkt darunter")
        report("Footprint", f"{tf}: POC, Imbalances 400 %, Stacked ≥3, Unfinished Auction", checked > 0 and not (poc_bad or imb_bad or stack_bad or auction_bad),
               f"POC {poc_bad}, Imbalance {imb_bad}, Stacked {stack_bad}, Auction {auction_bad} Kerzen abweichend (von {checked})")


def check_bubbles(raw: Raw) -> None:
    for tf in ("5m", "30m"):
        api = raw.api[tf].get("bubbles") or {}
        items = api.get("items") or []
        if not items:
            report("Volume Bubbles", tf, None, api.get("note") or "keine Bubbles")
            continue
        first, last = raw.api[tf]["candles"][0]["time"], raw.api[tf]["candles"][-1]["time"] + SECONDS[tf]
        mine = []
        days_ok = set(raw.archive_days) | {raw.t0.date().isoformat()}
        for key, item in raw.trades.items():
            if key not in days_ok:
                continue
            for ms, price, qty, side, usd in item["bubbles"]:
                if first <= ms / 1000 < last:
                    mine.append((usd, ms, price, qty, side))
        updated = epoch(raw.api[tf].get("trades_updated_at") or raw.t0.isoformat())
        covered = [i for i in items if utc(i["time"]).date().isoformat() in days_ok and i["time"] < updated - 120]
        mine_by = {(ms, side): (usd, price, qty) for usd, ms, price, qty, side in mine}
        missing = [i for i in covered if (round(i["time"] * 1000), i["side"]) not in mine_by]
        wrong = [i for i in covered if (round(i["time"] * 1000), i["side"]) in mine_by
                 and (abs(mine_by[(round(i["time"] * 1000), i["side"])][2] - i["quantity"]) > 1e-6 or abs(mine_by[(round(i["time"] * 1000), i["side"])][1] - i["price"]) > 0.01)]
        report("Volume Bubbles", f"{tf}: jede Bubble ist eine echte Taker-Order (Zeit, Seite, Menge, Preis)", bool(covered) and not missing and not wrong,
               f"{len(covered)} Bubbles geprüft, {len(missing)} nicht gefunden, {len(wrong)} mit anderer Menge/Preis")
        # the largest orders of the window must all be there (TIM sends the 400 largest)
        floor = min(i["usd"] for i in items)
        window_mine = sorted((m for m in mine if m[1] / 1000 < updated - 120 and utc(m[1] / 1000).date().isoformat() in days_ok), reverse=True)
        expected = [m for m in window_mine if m[0] > floor * 1.0001]
        shown = {(round(i["time"] * 1000), i["side"]) for i in items}
        lost = [m for m in expected if (m[1], m[4]) not in shown]
        report("Volume Bubbles", f"{tf}: alle Orders über der kleinsten gezeigten ({fmt(floor, 0)} USD) sind drin", not lost,
               f"{len(expected)} erwartet, {len(lost)} fehlen" + (f", größte fehlende {fmt(lost[0][0], 0)} USD am {utc(lost[0][1] / 1000):%d.%m. %H:%M}" if lost else ""))
        side_ok = all(i["side"] in (1, -1) for i in items)
        report("Volume Bubbles", f"{tf}: Seite (Käufer grün / Verkäufer rot) aus isBuyerMaker", side_ok and not wrong, "Seite stimmt bei allen gefundenen Orders")


# ---- gamma


def bs_gamma(s: float, k: float, t: float, vol: float) -> float:
    d1 = (math.log(s / k) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    return math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi) / (s * vol * math.sqrt(t))


def check_gamma(raw: Raw) -> None:
    api = load(raw.folder / "api_gamma.json")
    book = load(raw.folder / "deribit_book.json")
    if not api or not book:
        report("Options-Gamma", "Deribit-Daten", None, "nicht gelesen")
        return
    snap = api.get("snapshot", api) if isinstance(api, dict) else api
    if "levels" not in snap:
        snap = next((v for v in snap.values() if isinstance(v, dict) and "levels" in v), snap)
    spot = float(snap["spot"])
    as_of = datetime.fromisoformat(snap["as_of"])
    months = {m: i for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
    quotes = []
    for row in book["result"]:
        cur, exp, strike, kind = row["instrument_name"].split("-")
        expiry = datetime(2000 + int(exp[-2:]), months[exp[-5:-2]], int(exp[:-5]), 8, tzinfo=timezone.utc)
        oi, iv = row.get("open_interest") or 0, row.get("mark_iv") or 0
        if expiry <= as_of or oi <= 0 or iv <= 0 or abs(float(strike) / spot - 1) > 0.35:
            continue
        quotes.append((float(strike), expiry, kind == "C", float(oi), iv / 100))

    def gex(price: float, qs: list) -> float:
        total = 0.0
        for k, e, call, oi, vol in qs:
            t = (e - as_of).total_seconds() / (365 * 86400)
            g = bs_gamma(price, k, t, vol) * oi * price * price * 0.01
            total += g if call else -g
        return total

    levels = {lv["key"]: lv for lv in snap["levels"]}
    by_strike_call: dict[float, float] = {}
    by_strike_put: dict[float, float] = {}
    for k, e, call, oi, vol in quotes:
        t = (e - as_of).total_seconds() / (365 * 86400)
        g = bs_gamma(spot, k, t, vol) * oi * spot * spot * 0.01
        (by_strike_call if call else by_strike_put)[k] = (by_strike_call if call else by_strike_put).get(k, 0.0) + g
    call_wall = max((k for k in by_strike_call if k >= spot), key=lambda k: (by_strike_call[k], -k), default=None)
    put_wall = max((k for k in by_strike_put if k <= spot), key=lambda k: (by_strike_put[k], -k), default=None)
    grid = [spot * 0.85 + spot * 0.30 * i / 300 for i in range(301)]
    vals = [gex(p, quotes) for p in grid]
    flips = [p0 + (p1 - p0) * (-v0) / (v1 - v0) for p0, p1, v0, v1 in zip(grid, grid[1:], vals, vals[1:]) if (v0 < 0) != (v1 < 0)]
    flip = min(flips, key=lambda p: abs(p - spot)) if flips else None
    age = (raw.t0 - as_of).total_seconds() / 60
    tol = 0.01 * spot  # the book moves between TIM's read and ours
    for key, mine, name in (("call_wall", call_wall, "Call Wall"), ("put_wall", put_wall, "Put Wall"), ("flip", flip, "Gamma Flip")):
        d = levels.get(key)
        report("Options-Gamma", f"{name} = eigene Black-Scholes-Rechnung aus Deribit-Book", d is not None and mine is not None and abs(d["price"] - mine) <= tol,
               f"Chart {fmt(d['price'] if d else None, 0)} / eigen {fmt(mine, 0)} (Deribit-Stand {age:.0f} min auseinander)")
    main = next((lv for lv in snap["levels"] if lv["key"] == "max_pain"), None)
    if main:
        expiry = datetime.fromisoformat(snap["main_expiry"]["expiry"]) if "main_expiry" in snap else None
        qs = [q for q in quotes if q[1] == expiry]
        strikes = sorted({q[0] for q in qs})
        pain = min(strikes, key=lambda p: (sum(oi * (max(p - k, 0) if c else max(k - p, 0)) for k, e, c, oi, v in qs), p)) if strikes else None
        report("Options-Gamma", f"Max Pain {expiry:%d.%m.} = eigene Rechnung" if expiry else "Max Pain", pain is not None and abs(main["price"] - pain) <= tol,
               f"Chart {fmt(main['price'], 0)} / eigen {fmt(pain, 0)}")
    drawn = {d["name"] for d in raw.drawings("30m", "gamma")}
    report("Options-Gamma", "alle Gamma-Level im Chart gezeichnet", {lv["name"] for lv in snap["levels"]} <= drawn or not drawn and None,
           f"{len(drawn)} von {len(snap['levels'])} Leveln im Chart" + ("" if drawn else " (Stand evtl. veraltet → ausgeblendet)"))


# ---- liquidation estimate


def check_liquidation(raw: Raw) -> None:
    api = load(raw.folder / "api_liquidation.json")
    oi_rows = load(raw.folder / "fapi_oi.json")
    kl = load(raw.folder / "fapi_kl.json")
    if not api or not oi_rows or not kl:
        report("Liquidations-Heatmap", "Futures-Daten", None, "nicht gelesen")
        return
    est = api if "analysis" in api else next((v for v in api.values() if isinstance(v, dict) and "analysis" in v), api)
    oi = {int(r["timestamp"]) // 1000: float(r["sumOpenInterest"]) for r in oi_rows}
    latest = max(oi)
    now_oi = load(raw.folder / "fapi_oi_now.json")
    report("Liquidations-Heatmap", "Zeitstempel der OI-Historie = Periodenbeginn (Annahme des Modells)", None,
           f"neuester OI-Stand {utc(latest):%H:%M} UTC = {oi[latest]:,.0f} BTC, OI jetzt {float(now_oi['openInterest']):,.0f} BTC" if now_oi else f"neuester OI-Stand {utc(latest):%H:%M} UTC")
    candles = [(r[0] // 1000, float(r[2]), float(r[3]), float(r[4])) for r in kl]
    step = float(est["step"])
    mix = [(10, 0.30), (25, 0.30), (50, 0.25), (100, 0.15)]
    active: dict[tuple[str, float], float] = {}
    for t, high, low, close in candles:
        for key in [k for k in active if (k[0] == "long" and k[1] + step > low) or (k[0] == "short" and k[1] <= high)]:
            active.pop(key)
        before, after = oi.get(t), oi.get(t + 1800)
        if before is None or after is None or before <= 0:
            continue
        change = after - before
        if change < 0:
            for key in active:
                active[key] *= max(0.0, 1 + change / before)
            continue
        price = (high + low + close) / 3
        for lev, w in mix:
            for side, level in (("long", price * (1 - 1 / lev)), ("short", price * (1 + 1 / lev))):
                key = (side, round(math.floor(level / step + 1e-9) * step, 10))
                active[key] = active.get(key, 0.0) + change * price * w * 0.5
    last = candles[-1][3]

    def cluster(side: str, cond) -> float | None:
        rows = {k[1]: v for k, v in active.items() if k[0] == side and cond(k[1])}
        if not rows:
            return None
        best = max(rows, key=lambda r: sum(rows.get(round(r + i * step, 10), 0.0) for i in range(-2, 3)))
        return best + step / 2

    above = cluster("short", lambda p: p > last)
    below = cluster("long", lambda p: p + step <= last)
    for where, mine in (("above", above), ("below", below)):
        theirs = (est["analysis"].get(f"cluster_{where}") or {}).get("price")
        report("Liquidations-Heatmap", f"Cluster {'oben' if where == 'above' else 'unten'} = eigene Nachrechnung des Modells", theirs is not None and mine is not None and abs(theirs - mine) <= 3 * step,
               f"Chart {fmt(theirs, 0)} / eigen {fmt(mine, 0)} (Zeile {step:g} USDT; Zeitpunkt verschieden)")
    report("Liquidations-Heatmap", "als Schätzung gekennzeichnet", bool(est.get("estimate")), "estimate=True, Gruppe heißt „(Schätzung)“")


# ---- plans / position boxes


def check_plans(raw: Raw, journal_dir: Path | None) -> None:
    plans = raw.api["30m"].get("plans") or []
    if not plans:
        report("Positions-Boxen", "TIM-Pläne", None, "keine Pläne im 30m-Fenster")
        return
    times = [c["time"] for c in raw.api["30m"]["candles"]]
    problems = []
    for p in plans:
        if p["t1"] not in times or p["t2"] not in times or p["t2"] < p["t1"]:
            problems.append(f"{p['id']}: Zeiten nicht auf Kerzen")
        if p["direction"] == "LONG" and not (p["stop"] < p["entry"] and all(t > p["entry"] for t in p["targets"])):
            problems.append(f"{p['id']}: Long mit Stop/Zielen auf falscher Seite")
        if p["direction"] == "SHORT" and not (p["stop"] > p["entry"] and all(t < p["entry"] for t in p["targets"])):
            problems.append(f"{p['id']}: Short mit Stop/Zielen auf falscher Seite")
    report("Positions-Boxen", f"{len(plans)} Pläne: Seite von Stop/Zielen, Zeiten auf Kerzen", not problems, "; ".join(problems[:3]) if problems else "alle plausibel")
    if journal_dir and journal_dir.exists():
        entries = {}
        for path in journal_dir.glob("tim_plan_journal*.json"):
            try:
                data = json.loads(path.read_text())
            except Exception:  # noqa: BLE001
                continue
            for e in data.get("entries", data if isinstance(data, list) else []):
                if isinstance(e, dict) and e.get("id"):
                    entries[e["id"]] = e
        bad = []
        for p in plans:
            e = entries.get(p["id"])
            if not e:
                bad.append(f"{p['id']} nicht im Journal")
                continue
            if abs(p["entry"] - float(e.get("fill_price") or e["entry"])) > 1e-6 or abs(p["stop"] - float(e["stop"])) > 1e-6:
                bad.append(f"{p['id']} Einstieg/Stop ≠ Journal")
            for key, tkey in (("t1", "filled_at"), ("close_t", "closed_at")):
                when = e.get(tkey) or (e.get("created_at") if key == "t1" else None)
                if when and epoch(when) >= times[0]:
                    snapped = times[max(0, bisect_right(times, epoch(when)) - 1)]
                    if p[key] != snapped:
                        bad.append(f"{p['id']} {tkey} falsch eingerastet")
        report("Positions-Boxen", "Einstieg, Stop, Fill-/Schlusszeit = Plan-Journal (nur gelesen)", not bad, "; ".join(bad[:3]) if bad else f"{len(plans)} Pläne gleich dem Journal")


# ---- placement on the time axis


def check_placement(raw: Raw) -> None:
    problems = []
    for tf in VIEWS:
        api = raw.api[tf]
        times = [c["time"] for c in api["candles"]]
        for d in api["drawings"]:
            if d["t1"] not in times or d["t2"] not in times or d["t2"] < d["t1"]:
                problems.append(f"{tf} {d['label']}")
            elif not d.get("curve") and d["group"] != "trend" and d.get("start") and not d.get("clipped"):
                start = epoch(d["start"])
                want = times[max(0, bisect_right(times, start) - 1)]
                if d["t1"] != want and d["t1"] != times[-2]:
                    problems.append(f"{tf} {d['label']} Start {utc(d['t1']):%d.%m. %H:%M} statt {utc(want):%d.%m. %H:%M}")
    report("Zeitachse", "Jede Linie beginnt an der Kerze ihres Entstehens (alle Ansichten)", not problems, "; ".join(problems[:4]) if problems else "alle Linien richtig eingerastet")


def analyze(folder: Path, journal_dir: Path | None) -> int:
    raw = Raw(folder)
    report("Daten", "Rohdaten", None, f"API gelesen {raw.t0:%d.%m. %H:%M} UTC; Archive {sorted(raw.archive_days)[:1]}…{sorted(raw.archive_days)[-1:]}; heute REST {raw.meta.get('rest_today')}")
    for name, fn in (("Kerzen", lambda: check_candles(raw)), ("Extreme", lambda: check_extremes(raw))):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
            report(name, "Prüfung lief nicht", False, repr(exc))
    ours: dict[str, Any] = {}
    tpo: dict[str, Any] = {}
    steps = (("Volume Profile", lambda: ours.update(check_volume_profiles(raw))), ("TPO", lambda: tpo.update(check_tpo(raw))),
             ("Tageslevel", lambda: check_trade_levels(raw, ours)), ("naked POC", lambda: check_naked(raw, ours, tpo)),
             ("Sessions", lambda: check_sessions(raw)), ("BOS / MSS", lambda: check_structure(raw)), ("Trendlinien", lambda: check_trend(raw)),
             ("VWAP", lambda: check_vwap(raw)), ("Fibonacci", lambda: check_fib(raw)), ("Footprint", lambda: check_footprint(raw)),
             ("Volume Bubbles", lambda: check_bubbles(raw)), ("Options-Gamma", lambda: check_gamma(raw)),
             ("Liquidations-Heatmap", lambda: check_liquidation(raw)), ("Positions-Boxen", lambda: check_plans(raw, journal_dir)),
             ("Zeitachse", lambda: check_placement(raw)))
    for name, fn in steps:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            import traceback
            report(name, "Prüfung lief nicht", False, repr(exc) + " " + traceback.format_exc().splitlines()[-3])
    save(folder / "audit_results.json", RESULTS)
    lines = ["| Indikator | Prüfung | Ergebnis | Detail |", "|---|---|---|---|"]
    lines += [f"| {r['indicator']} | {r['check']} | {r['result']} | {r['detail']} |" for r in RESULTS]
    (folder / "audit_results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    counts = {k: sum(r["result"] == k for r in RESULTS) for k in ("PASS", "FAIL", "INFO")}
    print(json.dumps(counts))
    return 1 if counts["FAIL"] else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--base", default="http://127.0.0.1:8765")
    c.add_argument("--out", required=True, type=Path)
    c.add_argument("--archive-cache", type=Path, default=None)
    c.add_argument("--days", type=int, default=14, help="finished days read from the Binance archive")
    a = sub.add_parser("analyze")
    a.add_argument("--raw", required=True, type=Path)
    a.add_argument("--journal-dir", type=Path, default=None, help="folder with tim_plan_journal*.json (read only)")
    args = parser.parse_args(argv)
    if args.command == "collect":
        collect(args.base.rstrip("/"), args.out, args.archive_cache or args.out / "archive", args.days)
        return 0
    return analyze(args.raw, args.journal_dir)


if __name__ == "__main__":
    sys.exit(main())
