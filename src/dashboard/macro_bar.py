"""Macro bar for the prep page: gold, US dollar, Nasdaq, 10-year yield and BTC dominance next to BTC.

Display only (Uzi 27.10.2026: gold and the big markets into the analysis). Nothing here
feeds a score, a plan or an order. For every market the bar shows the latest daily value,
the change over five observations, the position against the 20-day mean and the 30-day
correlation of daily changes with BTC.

Sources (public, no key):
- BTC and gold: Binance spot daily klines (BTCUSDT, PAXGUSDT = tokenised gold).
- US dollar, Nasdaq, 10-year yield: FRED CSV (DTWEXBGS, NASDAQCOM, DGS10). FRED publishes
  with a delay (the broad dollar index about a week), so every row shows its own date.
- BTC dominance: CoinGecko /global, a snapshot only. TIM stores one value per UTC day in
  ``data/macro/btc_dominance.jsonl`` and builds its own history from there.
"""

from __future__ import annotations

import csv
import io
import json
import math
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.request import Request, urlopen

TTL = 3600.0  # seconds; daily data, one fetch per hour is plenty
FAIL_PAUSE = 300.0  # seconds without new requests after a failure
CORR_DAYS = 30
MEAN_DAYS = 20
CHANGE_STEPS = 5
MIN_OVERLAP = 20  # common days needed for a correlation
DOMINANCE_PATH = Path("data/macro/btc_dominance.jsonl")
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
BINANCE_KLINES = "https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=120"


@dataclass(frozen=True)
class Market:
    key: str
    name: str
    source: str
    ref: str
    unit: str  # "pct" = relative change, "bp" = change in basis points (yields)
    note: str = ""


MARKETS: tuple[Market, ...] = (
    Market("gold", "Gold (PAXG)", "binance", "PAXGUSDT", "pct", "tokenisiertes Gold, handelt auch am Wochenende"),
    Market("dollar", "US-Dollar (Fed Broad Index)", "fred", "DTWEXBGS", "pct", "FRED, etwa eine Woche Verzug"),
    Market("nasdaq", "Nasdaq Composite", "fred", "NASDAQCOM", "pct", "FRED, Schlusskurs Vortag"),
    Market("us10y", "US-Zins 10 Jahre", "fred", "DGS10", "bp", "FRED, Rendite in %"),
)

Series = list[tuple[date, float]]
Fetch = Callable[[str], bytes]


def _http(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "TIM-dashboard/1.0", "Accept": "*/*"})
    with urlopen(request, timeout=8) as response:  # noqa: S310 - fixed public https endpoints above
        return response.read()


def parse_fred(raw: bytes) -> Series:
    """FRED CSV (date, value); '.' marks a missing day and is skipped."""
    rows = csv.reader(io.StringIO(raw.decode("utf-8", "replace")))
    next(rows, None)
    out: Series = []
    for row in rows:
        if len(row) < 2:
            continue
        try:
            out.append((date.fromisoformat(row[0]), float(row[1])))
        except ValueError:
            continue
    return out


def parse_klines(raw: bytes, now: datetime) -> Series:
    """Binance daily klines; the running day is left out (only closed candles)."""
    out: Series = []
    for row in json.loads(raw):
        close_ms = int(row[6])
        if close_ms >= now.timestamp() * 1000:
            continue
        out.append((datetime.fromtimestamp(int(row[0]) / 1000, timezone.utc).date(), float(row[4])))
    return out


def parse_dominance(raw: bytes) -> float | None:
    try:
        value = json.loads(raw)["data"]["market_cap_percentage"]["btc"]
    except (KeyError, TypeError, ValueError):
        return None
    return float(value) if isinstance(value, (int, float)) and 0 < value < 100 else None


def _changes(series: Series, unit: str) -> dict[date, float]:
    """Daily change per date: relative for prices, absolute for yields."""
    out = {}
    for (_, prev), (day, value) in zip(series, series[1:]):
        if unit == "bp":
            out[day] = value - prev
        elif prev:
            out[day] = value / prev - 1
    return out


def correlation(a: Mapping[date, float], b: Mapping[date, float], days: int = CORR_DAYS) -> tuple[float | None, int]:
    """Pearson correlation of the last ``days`` common dates; None below MIN_OVERLAP."""
    common = sorted(set(a) & set(b))[-days:]
    if len(common) < MIN_OVERLAP:
        return None, len(common)
    xs, ys = [a[d] for d in common], [b[d] for d in common]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None, len(common)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy), len(common)


def relation_text(value: float | None) -> str:
    if value is None:
        return "zu wenig gemeinsame Tage"
    if value >= 0.4:
        return "läuft meist mit BTC"
    if value <= -0.4:
        return "läuft meist gegen BTC"
    return "kaum Zusammenhang"


def describe(series: Series, unit: str, btc_changes: Mapping[date, float] | None) -> dict[str, Any]:
    """Latest value, 5-step change, position vs. 20-day mean and correlation with BTC."""
    if len(series) < 2:
        return {"status": "UNAVAILABLE"}
    last_day, last = series[-1]
    base = series[-1 - CHANGE_STEPS][1] if len(series) > CHANGE_STEPS else series[0][1]
    change = (last - base) * 100 if unit == "bp" else ((last / base - 1) * 100 if base else None)
    window = [v for _, v in series[-MEAN_DAYS:]]
    mean = sum(window) / len(window)
    corr, overlap = correlation(_changes(series, unit), btc_changes) if btc_changes is not None else (None, 0)
    return {"status": "OK", "last": last, "date": last_day.isoformat(), "change": change, "change_unit": "bp" if unit == "bp" else "%",
            "above_mean": last > mean if len(window) >= MEAN_DAYS else None, "corr_btc": corr, "overlap": overlap,
            "relation": relation_text(corr) if btc_changes is not None else None}


def record_dominance(path: Path, value: float, now: datetime) -> list[dict[str, Any]]:
    """Append today's BTC dominance once per UTC day and return the stored history (oldest first)."""
    history = load_dominance(path)
    today = now.date().isoformat()
    if not history or history[-1]["date"] != today:
        entry = {"date": today, "btc_dominance": round(value, 3), "observed_at": now.isoformat(), "source": "coingecko_global"}
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        history.append(entry)
    return history


def load_dominance(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
            out.append({"date": str(item["date"]), "btc_dominance": float(item["btc_dominance"]), **{k: v for k, v in item.items() if k not in ("date", "btc_dominance")}})
        except (ValueError, KeyError, TypeError):
            continue
    return out


def build_macro_bar(fetch: Fetch = _http, now: datetime | None = None, dominance_path: Path = DOMINANCE_PATH) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    notes: list[str] = []
    start = date(now.year - 1, now.month, 1).isoformat()  # one year back is enough for 120 daily values

    def load(market_source: str, ref: str) -> Series:
        try:
            if market_source == "binance":
                return parse_klines(fetch(BINANCE_KLINES.format(symbol=ref)), now)
            return parse_fred(fetch(FRED_URL.format(series=ref, start=start)))[-120:]
        except Exception as exc:  # noqa: BLE001 - one missing source must not drop the bar
            notes.append(f"{ref}: nicht erreichbar ({type(exc).__name__}).")
            return []

    btc = load("binance", "BTCUSDT")
    btc_changes = _changes(btc, "pct") if btc else None
    rows = [{"key": "btc", "name": "Bitcoin", "note": "Binance Spot", **describe(btc, "pct", None)}]
    for market in MARKETS:
        rows.append({"key": market.key, "name": market.name, "note": market.note, **describe(load(market.source, market.ref), market.unit, btc_changes)})

    dominance: dict[str, Any] = {"key": "btc_dominance", "name": "BTC-Dominanz", "note": "CoinGecko, TIM speichert einen Wert je Tag", "status": "UNAVAILABLE"}
    try:
        value = parse_dominance(fetch(COINGECKO_GLOBAL))
    except Exception as exc:  # noqa: BLE001
        value = None
        notes.append(f"BTC-Dominanz: nicht erreichbar ({type(exc).__name__}).")
    history = record_dominance(dominance_path, value, now) if value is not None else load_dominance(dominance_path)
    if history:
        series = [(date.fromisoformat(h["date"]), h["btc_dominance"]) for h in history]
        dominance.update(describe(series, "bp", btc_changes))
        dominance["change_unit"] = "Prozentpunkte"
        if dominance.get("change") is not None:
            dominance["change"] = dominance["change"] / 100  # bp of a percentage -> percentage points
        dominance["days_stored"] = len(history)
        if value is not None:
            dominance["last"] = value
    rows.append(dominance)
    return {"generated_at": now.isoformat(), "rows": rows, "notes": notes, "read_only": True,
            "provenance": "Binance klines, FRED CSV, CoinGecko global (display only)"}


class MacroCache:
    """One macro bar per hour, built in a background thread so a page never waits for FRED.

    ``snapshot()`` returns the last bar (or None before the first one) and starts a refresh
    when it is stale; after a failed build it waits FAIL_PAUSE before trying again.
    """

    def __init__(self, build: Callable[[], dict[str, Any]] | None = None) -> None:
        self._build = build or build_macro_bar
        self._lock = threading.Lock()
        self._value: dict[str, Any] | None = None
        self._at = -math.inf
        self._running = False

    def _stale(self) -> bool:
        failed = self._value is None or all(r.get("status") != "OK" for r in self._value.get("rows", []))
        return time.monotonic() - self._at >= (FAIL_PAUSE if failed else TTL)

    def refresh(self) -> dict[str, Any] | None:
        try:
            value = self._build()
        except Exception:  # noqa: BLE001 - keep the last bar
            value = None
        with self._lock:
            if value is not None:
                self._value = value
            self._at, self._running = time.monotonic(), False
            return self._value

    def snapshot(self, background: bool = True) -> dict[str, Any] | None:
        with self._lock:
            start = self._stale() and not self._running
            if start:
                self._running = True
            value = self._value
        if start:
            if background:
                threading.Thread(target=self.refresh, name="tim-macro-bar", daemon=True).start()
            else:
                value = self.refresh()
        return value


CACHE = MacroCache()


def macro_rows_html(macro: Mapping[str, Any] | None, safe: Callable[[Any], str]) -> str:
    """Section for the prep page; ``None`` = first bar still loading."""
    if macro is None:
        return ("<section class='cc-section'><p class='cc-section__eyebrow'>0 · Umfeld</p><h2>Makro</h2>"
                "<p class='empty'>Makro-Daten werden geladen (Gold, Dollar, Nasdaq, Zinsen, BTC-Dominanz). Seite in einer Minute neu laden.</p></section>")
    def num(value: Any, digits: int = 2) -> str:
        return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",") if isinstance(value, (int, float)) else "–"

    rows = []
    for row in macro.get("rows") or []:
        if row.get("status") != "OK":
            rows.append(f"<tr><td>{safe(row['name'])}</td><td colspan='5' class='empty'>keine Daten</td></tr>")
            continue
        unit = row.get("change_unit", "%")
        change = f"{row['change']:+.2f}".replace(".", ",") + (" %" if unit == "%" else " bp" if unit == "bp" else " P.") if isinstance(row.get("change"), (int, float)) else "–"
        trend = {True: "über 20-Tage-Schnitt", False: "unter 20-Tage-Schnitt", None: "–"}[row.get("above_mean")]
        corr = row.get("corr_btc")
        corr_text = "–" if row["key"] == "btc" else (f"{corr:+.2f}".replace(".", ",") + f" · {row.get('relation')}" if corr is not None else (row.get("relation") or "–"))
        stored = f" ({row['days_stored']} Tage gespeichert)" if row.get("days_stored") else ""
        rows.append(f"<tr><td>{safe(row['name'])}<br><small>{safe(row.get('note'))}{safe(stored)}</small></td><td class='mono'>{safe(num(row.get('last')))}</td>"
                    f"<td>{safe(row.get('date', '')[8:10])}.{safe(row.get('date', '')[5:7])}.</td><td class='mono'>{safe(change)}</td><td>{safe(trend)}</td><td>{safe(corr_text)}</td></tr>")
    notes = "".join(f"<li>{safe(n)}</li>" for n in macro.get("notes") or [])
    return (
        "<section class='cc-section'><div class='cc-section__head'><div><p class='cc-section__eyebrow'>0 · Umfeld</p>"
        "<h2>Makro: Gold, Dollar, Aktien, Zinsen, BTC-Dominanz</h2><p class='cc-section__note'>Tageswerte. Änderung über 5 Werte, "
        "Lage zum 20-Tage-Schnitt und Zusammenhang der Tagesänderungen mit BTC über 30 gemeinsame Tage (+1 = gleichläufig, −1 = gegenläufig). "
        "Nur Kontext, kein Signal.</p></div></div>"
        "<div class='table-wrap'><table><thead><tr><th>Markt</th><th>Wert</th><th>Stand</th><th>Änderung</th><th>Trend</th><th>Zusammenhang mit BTC</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
        + (f"<ul class='cc-list'>{notes}</ul>" if notes else "") + "</section>"
    )
