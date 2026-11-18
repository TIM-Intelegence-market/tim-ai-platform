"""USDT dominance (USDT.D) as a display market on the TIM chart (Uzi 18.11.2026, TradingView "Market Cap USDT Dominance").

USDT.D = market cap of Tether / total crypto market cap, in percent. TradingView's CRYPTOCAP series is not
copied. TIM computes its own value:

- Recorder: CoinGecko ``/global`` (``market_cap_percentage.usdt``, public, no key) is read every 5 minutes
  and stored as one line per sample in ``data/macro/usdt_dominance_samples.jsonl``. Candles (open, high, low,
  close of the samples) of every interval from 5 minutes up are built from these samples. A free hourly
  history of the total market cap does not exist (CoinGecko's chart is Pro only), so hourly and shorter
  candles start with the first recorded sample and fill up from there.
- Daily history: the Coin Metrics series TIM already uses (``market_context.DOMINANCE``, about 830 assets, daily)
  fills 1d and longer views for the days before the recording. These days are flat candles (one value per
  day, no high/low) and are marked in the note.

Display only: no score, no plan, no order. The influence study of 07.11.2026 found no lead and no filter value
in dominance; the chart shows it for orientation and as the inverse picture to BTC.
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any, Callable, Mapping, Sequence

SYMBOL = "USDTD"
NAME = "USDT-Dominanz (USDT.D)"
TAB = "USDT.D"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
SAMPLES_PATH = Path("data/macro/usdt_dominance_samples.jsonl")
SAMPLE_EVERY = 300.0  # seconds between reads
KEEP_SECONDS = 400 * 86400
OFFERED = ("5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d", "3d", "1w", "1M")
EMA_FAST, EMA_SLOW = 20, 50
SOURCE_NOTE = ("USDT-Dominanz = Tether-Marktkapitalisierung / gesamte Krypto-Marktkapitalisierung (eigene Aufzeichnung "
               "aus CoinGecko /global alle 5 Minuten, kein TradingView-Wert; Abweichung zu CRYPTOCAP möglich). "
               "Kerzen bis 12 h beginnen mit der ersten Aufzeichnung; Tage davor kommen aus Coin Metrics "
               "(täglich, nur Schlusswerte als flache Kerzen). Nur Anzeige, kein Signal: die Dominanz-Studie vom 07.11. fand keinen Vorlauf.")


def parse_global(raw: bytes | str) -> tuple[float, float | None, float | None]:
    """USDT dominance %, BTC dominance % and total market cap (USD) from CoinGecko ``/global``."""
    data = json.loads(raw)["data"]
    usdt = float(data["market_cap_percentage"]["usdt"])
    if isinstance(usdt, bool) or not 0 < usdt < 100:
        raise ValueError("usdt dominance out of range")
    btc = data["market_cap_percentage"].get("btc")
    total = (data.get("total_market_cap") or {}).get("usd")
    return usdt, float(btc) if isinstance(btc, (int, float)) else None, float(total) if isinstance(total, (int, float)) else None


def load_samples(path: Path = SAMPLES_PATH, now: datetime | None = None) -> list[dict[str, float]]:
    """Stored samples, oldest first; broken lines are skipped, anything older than 400 days is dropped."""
    now = now or datetime.now(timezone.utc)
    out: list[dict[str, float]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            item = json.loads(line)
            t, usdt = int(item["t"]), float(item["usdt"])
        except (ValueError, KeyError, TypeError):
            continue
        if 0 < usdt < 100 and now.timestamp() - t <= KEEP_SECONDS and (not out or t > out[-1]["t"]):
            out.append({"t": t, "usdt": usdt})
    return out


def record_sample(path: Path, usdt: float, now: datetime, btc: float | None = None, total: float | None = None) -> bool:
    """Append one sample; False when the last one is younger than 4 minutes (no double reads)."""
    last = load_samples(path, now)[-1:] if path.exists() else []
    if last and now.timestamp() - last[0]["t"] < SAMPLE_EVERY - 60:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"t": int(now.timestamp()), "usdt": round(usdt, 5)}
    if btc is not None:
        entry["btc"] = round(btc, 4)
    if total is not None:
        entry["total"] = round(total)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return True


def _http(url: str) -> bytes:
    from urllib.request import Request, urlopen

    request = Request(url, headers={"User-Agent": "TIM-dashboard/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=10) as response:  # noqa: S310 - fixed public https endpoint
        return response.read(1_000_001)


class Recorder:
    """Reads CoinGecko every 5 minutes in one background thread; a failed read is skipped, never filled."""

    def __init__(self, path: Path = SAMPLES_PATH, fetch: Callable[[str], bytes] = _http, every: float = SAMPLE_EVERY) -> None:
        self.path, self.fetch, self.every = path, fetch, every
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None

    def once(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        try:
            usdt, btc, total = parse_global(self.fetch(COINGECKO_GLOBAL))
        except Exception as exc:  # noqa: BLE001 - network trouble must not break the page
            self.last_error = type(exc).__name__
            return False
        self.last_error = None
        try:
            return record_sample(self.path, usdt, now, btc, total)
        except OSError as exc:
            self.last_error = type(exc).__name__
            return False

    def _loop(self) -> None:
        while True:
            self.once()
            time.sleep(self.every)

    def start(self) -> None:
        if os.environ.get("TIM_RUNTIME_ENV") == "test":
            return
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._loop, name="tim-usdt-dominance", daemon=True)
                self._thread.start()


RECORDER = Recorder()


def chart_context() -> dict[str, Any] | None:
    """Samples plus the daily Coin Metrics series for one chart request (starts the recorder on first use)."""
    if os.environ.get("TIM_RUNTIME_ENV") == "test":
        return None
    from src.dashboard.market_context import DOMINANCE

    RECORDER.start()
    return {"samples": load_samples(), "daily": DOMINANCE.snapshot(), "error": RECORDER.last_error}


# --- candles -----------------------------------------------------------------------------------------------


def _bucket_bars(points: Sequence[tuple[int, float]], size: int) -> list[list[float]]:
    bars: dict[int, list[float]] = {}
    for t, value in points:
        start = t // size * size
        bar = bars.get(start)
        if bar is None:
            bars[start] = [start, value, value, value, value]
        else:
            bar[2], bar[3], bar[4] = max(bar[2], value), min(bar[3], value), value
    return [bars[k] for k in sorted(bars)]


def _daily_bars(samples: Sequence[Mapping[str, float]], daily: Mapping[str, Any] | None) -> list[list[float]]:
    """Daily bars: Coin Metrics (flat) for days without samples, sample OHLC for recorded days."""
    out = {int(b[0]): b for b in _bucket_bars([(int(s["t"]), float(s["usdt"])) for s in samples], 86400)}
    for stamp, _btc, usdt in (daily or {}).get("points", []):
        day = int(stamp) - 86400
        out.setdefault(day, [day, usdt, usdt, usdt, usdt])
    return [out[k] for k in sorted(out)]


def _regroup(bars: Sequence[Sequence[float]], key: Callable[[int], int]) -> list[list[float]]:
    groups: dict[int, list[Sequence[float]]] = {}
    for bar in bars:
        groups.setdefault(key(int(bar[0])), []).append(bar)
    return [[start, g[0][1], max(b[2] for b in g), min(b[3] for b in g), g[-1][4]] for start, g in sorted(groups.items())]


def _month_start(t: int) -> int:
    d = datetime.fromtimestamp(t, timezone.utc)
    return int(datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp())


def candle_rows(context: Mapping[str, Any] | None, timeframe: str, seconds: int, now: datetime) -> list[dict[str, Any]]:
    """Candle rows (the same shape ``clean_candles`` reads) for one view; empty when there is nothing recorded yet."""
    samples = (context or {}).get("samples") or []
    daily = (context or {}).get("daily")
    if seconds >= 86400:
        base = _daily_bars(samples, daily)
        if timeframe == "3d":
            bars = _regroup(base, lambda t: t // 259200 * 259200)
        elif timeframe == "1w":
            bars = _regroup(base, lambda t: (t // 86400 + 3) // 7 * 7 * 86400 - 3 * 86400)  # weeks start Monday
        elif timeframe == "1M":
            bars = _regroup(base, _month_start)
        else:
            bars = base
        provenance = "COINGECKO_GLOBAL_AND_COINMETRICS_DISPLAY"
    else:
        bars = _bucket_bars([(int(s["t"]), float(s["usdt"])) for s in samples], seconds)
        provenance = "COINGECKO_GLOBAL_RECORDED_DISPLAY"
    rows = []
    for t, o, h, lo, c in bars[-1000:]:
        opened = datetime.fromtimestamp(t, timezone.utc)
        end = datetime.fromtimestamp(t + (seconds if timeframe != "1M" else 2678400), timezone.utc)
        rows.append({"symbol": SYMBOL, "timeframe": timeframe, "open_time": opened.isoformat(), "close_time": end.isoformat(),
                     "open": o, "high": h, "low": lo, "close": c, "volume": 0.0, "provenance": provenance, "closed": end <= now})
    return rows


# --- indicators --------------------------------------------------------------------------------------------


def ema(values: Sequence[float], length: int) -> list[float | None]:
    """Exponential moving average; None until ``length`` values exist (seeded with their simple mean)."""
    out: list[float | None] = [None] * len(values)
    if len(values) < length:
        return out
    k = 2.0 / (length + 1)
    prev = fmean(values[:length])
    out[length - 1] = prev
    for i in range(length, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def swing_threshold(candles: Sequence[Mapping[str, Any]]) -> float:
    """Move against a swing before it counts: 3 average candle ranges, at least 0.02 percentage points."""
    ranges = [c["high"] - c["low"] for c in candles[-100:]]
    return max(0.02, 3 * fmean(ranges)) if ranges else 0.02


def indicator_drawings(candles: Sequence[Mapping[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    """Swing marks with values (as on the TradingView picture), EMA 20/50 and the two newest swing levels as support/resistance."""
    from src.dashboard.chart_live import zigzag_pivots

    closed = [c for c in candles if c.get("closed", True)]
    out: list[dict[str, Any]] = []
    if len(closed) < 5:
        return out
    pivots, running = zigzag_pivots(closed, swing_threshold(closed))
    marks = pivots[-8:] + ([running] if running else [])
    for p in marks:
        high = p["kind"] == "HIGH"
        end = min(len(candles) - 1, p["index"] + 12)  # short segment, long enough for its value label
        if end <= p["index"]:
            continue
        value = f"{p['price']:.4f}".replace(".", ",")
        out.append({"group": "usdtd_swing", "tf": timeframe, "name": f"{'Hoch' if high else 'Tief'} {value}",
                    "label": f"{value} {'↓' if high else '↑'}", "price": p["price"], "start": closed[p["index"]]["open_time"].isoformat(),
                    "end": candles[end]["open_time"].isoformat(), "broken": True,
                    "note": "Swing-Hoch" if high else "Swing-Tief"})
    for kind, name in (("HIGH", "Widerstand"), ("LOW", "Unterstützung")):
        newest = [p for p in pivots if p["kind"] == kind][-1:]
        if newest:
            p = newest[0]
            out.append({"group": "usdtd_sr", "tf": timeframe, "name": name, "label": f"{timeframe} {name}", "price": p["price"],
                        "start": closed[p["index"]]["open_time"].isoformat(),
                        "note": f"letztes Swing-{'Hoch' if kind == 'HIGH' else 'Tief'} als Marke, kein Signal"})
    closes = [c["close"] for c in closed]
    for length, color in ((EMA_FAST, "#f5c542"), (EMA_SLOW, "#5ec8d8")):
        line = ema(closes, length)
        curve = [[int(closed[i]["open_time"].timestamp()), v] for i, v in enumerate(line) if v is not None]
        if len(curve) >= 2:
            out.append({"group": "usdtd_ema", "tf": timeframe, "name": f"EMA {length}", "label": f"EMA {length}", "price": curve[-1][1],
                        "start": closed[length - 1]["open_time"].isoformat(), "color": color, "curve": curve,
                        "note": f"gleitender Durchschnitt über {length} Kerzen"})
    return out
