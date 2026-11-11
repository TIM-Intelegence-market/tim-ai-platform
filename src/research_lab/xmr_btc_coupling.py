"""How strongly Monero (XMR) follows Bitcoin: co-movement, beta and lead/lag, descriptive only.

Barti, 11.11.2026: "ich will es am ende so haben, dass tim mit xmr genau das macht wie mit btc, und es muss
auch berücksichtigt werden, dass xmr sehr an btc hängt". Before TIM uses BTC's state on XMR plans (Bauplan
XMR, Paket 4) this measures how strong the link really is, instead of assuming it.

Data (public, no key, no account):

* Binance USD-M monthly klines from data.binance.vision for XMRUSDT and BTCUSDT (the same market TIM collects
  live for XMR), each archive verified against Binance's own ``.CHECKSUM`` file before it is used.
* Optional cross-check: a Kraken OHLCVT CSV of the pair XMR/XBT (Kraken's downloadable history, columns
  ``time, open, high, low, close, volume, trades``). Kraken is a second, independent venue; its XMR/BTC price
  is compared with Binance's XMRUSDT / BTCUSDT ratio day by day.

What it computes per interval (15m, 1h, 1d), on log returns of candles that both markets have:

* ``corr``: correlation of the returns (co-movement), ``beta``: XMR % per 1 % BTC, ``r2``: share of XMR's
  variance BTC explains, ``own_share``: the rest (XMR's own movement),
* the same correlation on the 10 % worst BTC candles (crashes) and on the rest,
* lead/lag: correlation of XMR now with BTC ``k`` candles earlier (k > 0: BTC leads) for k = -3..3,
* per calendar year, and on 1d the spread of the rolling 30-day correlation (how unstable the link is).

Only 2020-2024: the holdout from 2025-01-01 stays closed (protocol), months from 2025 on are refused.
Nothing here trades, writes a rule or touches the plan journals. Run it where Binance is reachable (Mac/server):

    python -m src.research_lab.xmr_btc_coupling --out data/research_lab/xmr_btc_coupling
    python -m src.research_lab.xmr_btc_coupling --kraken ~/Downloads/XMRXBT_1440.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence

from src.research_lab.data.parse import parse_klines, read_single_csv
from src.research_lab.protocol import HOLDOUT_START_MS
from src.v2_readiness.backfill import parse_official_checksum, verify_archive

VERSION = "xmr-btc-coupling/1"
BASE_URL = "https://data.binance.vision/data/futures/um/monthly/klines"
SYMBOLS = ("XMRUSDT", "BTCUSDT")
INTERVALS = ("15m", "1h", "1d")
INTERVAL_MS = {"15m": 900_000, "1h": 3_600_000, "1d": 86_400_000}
FIRST_MONTH = (2020, 3)  # first full month of the XMRUSDT perpetual on Binance USD-M
LAST_MONTH = (2024, 12)  # the holdout starts 2025-01-01
LAGS = (-3, -2, -1, 0, 1, 2, 3)
CRASH_SHARE = 0.10  # the worst 10 % of BTC candles count as crash candles
ROLLING_DAYS = 30
DEFAULT_OUT = Path("data/research_lab/xmr_btc_coupling")

Fetcher = Callable[[str], bytes]


class HoldoutRefused(ValueError):
    """A month at or after 2025-01 was requested."""


class MissingArchive(LookupError):
    """Binance has no archive for this month (e.g. before the perpetual was listed)."""


def http_fetch(url: str, timeout: float = 60.0) -> bytes:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed https host
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise MissingArchive(url) from error
        raise


def months(first: tuple[int, int] = FIRST_MONTH, last: tuple[int, int] = LAST_MONTH) -> list[tuple[int, int]]:
    out, (year, month) = [], first
    while (year, month) <= last:
        out.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def month_start_ms(year: int, month: int) -> int:
    return int(datetime(year, month, 1, tzinfo=timezone.utc).timestamp() * 1000)


def archive_url(symbol: str, interval: str, year: int, month: int) -> str:
    if symbol not in SYMBOLS or interval not in INTERVAL_MS:
        raise ValueError(f"unsupported symbol/interval {symbol} {interval}")
    if month_start_ms(year, month) >= HOLDOUT_START_MS:
        raise HoldoutRefused(f"{year:04d}-{month:02d} lies in the holdout (from 2025-01-01)")
    return f"{BASE_URL}/{symbol}/{interval}/{symbol}-{interval}-{year:04d}-{month:02d}.zip"


def load_month(symbol: str, interval: str, year: int, month: int, cache: Path | None, fetch: Fetcher = http_fetch) -> dict[int, float]:
    """Close prices by open time (ms) of one verified monthly archive; cached as the verified zip."""
    url = archive_url(symbol, interval, year, month)
    name = url.rsplit("/", 1)[-1]
    path = cache / symbol / interval / name if cache else None
    if path and path.exists():
        payload = path.read_bytes()
    else:
        payload = fetch(url)
        digest = parse_official_checksum(fetch(url + ".CHECKSUM").decode("utf-8"), expected_filename=name)
        if not verify_archive(payload, digest):
            raise ValueError(f"checksum mismatch for {name}")
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
    start, end = month_start_ms(year, month), month_start_ms(*months((year, month), (year + 1, 12))[1])
    return {k.open_time: k.close for k in parse_klines(read_single_csv(payload)) if start <= k.open_time < end and k.close > 0}


def load_closes(symbol: str, interval: str, cache: Path | None, fetch: Fetcher = http_fetch,
                span: Sequence[tuple[int, int]] | None = None) -> tuple[dict[int, float], list[str]]:
    closes: dict[int, float] = {}
    missing: list[str] = []
    for year, month in span or months():
        try:
            closes.update(load_month(symbol, interval, year, month, cache, fetch))
        except MissingArchive:
            missing.append(f"{year:04d}-{month:02d}")
    return closes, missing


# ---------------------------------------------------------------- statistics (pure Python, no numpy)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def _corr_beta(x: Sequence[float], y: Sequence[float]) -> tuple[float | None, float | None]:
    """Correlation of x and y, and the beta of y on x (y = a + beta * x)."""
    if len(x) < 3:
        return None, None
    mx, my = _mean(x), _mean(y)
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    if sxx <= 0 or syy <= 0:
        return None, None
    return sxy / math.sqrt(sxx * syy), sxy / sxx


@dataclass(frozen=True, slots=True)
class Pairs:
    """Aligned log returns: ``times[i]`` is the open time of the candle whose return is ``btc[i]`` / ``xmr[i]``."""

    times: list[int]
    btc: list[float]
    xmr: list[float]


def aligned_returns(btc: Mapping[int, float], xmr: Mapping[int, float], step_ms: int) -> Pairs:
    """Log returns over one candle where both markets have this candle and the one before (gaps drop out)."""
    times, rb, rx = [], [], []
    for t in sorted(set(btc) & set(xmr)):
        prev = t - step_ms
        if prev in btc and prev in xmr:
            times.append(t)
            rb.append(math.log(btc[t] / btc[prev]))
            rx.append(math.log(xmr[t] / xmr[prev]))
    return Pairs(times, rb, rx)


def lead_lag(pairs: Pairs, step_ms: int, lags: Iterable[int] = LAGS) -> dict[int, float | None]:
    """corr(XMR at t, BTC at t - k); k > 0 means BTC moved first. Only exact time matches count."""
    index = {t: i for i, t in enumerate(pairs.times)}
    out: dict[int, float | None] = {}
    for k in lags:
        xs, ys = [], []
        for i, t in enumerate(pairs.times):
            j = index.get(t - k * step_ms)
            if j is not None:
                xs.append(pairs.btc[j])
                ys.append(pairs.xmr[i])
        out[k] = _corr_beta(xs, ys)[0]
    return out


def coupling(pairs: Pairs, step_ms: int) -> dict[str, object]:
    corr, beta = _corr_beta(pairs.btc, pairs.xmr)
    result: dict[str, object] = {"n": len(pairs.times), "corr": corr, "beta": beta,
                                 "r2": corr * corr if corr is not None else None,
                                 "own_share": 1 - corr * corr if corr is not None else None}
    if len(pairs.times) >= 20:
        cut = sorted(pairs.btc)[max(0, int(len(pairs.btc) * CRASH_SHARE) - 1)]
        crash = [i for i, r in enumerate(pairs.btc) if r <= cut]
        calm = [i for i, r in enumerate(pairs.btc) if r > cut]
        result["corr_crash"] = _corr_beta([pairs.btc[i] for i in crash], [pairs.xmr[i] for i in crash])[0]
        result["corr_rest"] = _corr_beta([pairs.btc[i] for i in calm], [pairs.xmr[i] for i in calm])[0]
    result["lead_lag"] = {str(k): v for k, v in lead_lag(pairs, step_ms).items()}
    return result


def by_year(pairs: Pairs) -> dict[str, dict[str, object]]:
    years: dict[int, list[int]] = {}
    for i, t in enumerate(pairs.times):
        years.setdefault(datetime.fromtimestamp(t / 1000, timezone.utc).year, []).append(i)
    out = {}
    for year, idx in sorted(years.items()):
        corr, beta = _corr_beta([pairs.btc[i] for i in idx], [pairs.xmr[i] for i in idx])
        out[str(year)] = {"n": len(idx), "corr": corr, "beta": beta}
    return out


def rolling_corr(pairs: Pairs, window_ms: int) -> dict[str, float | None]:
    """Spread of the correlation over rolling windows (one value per window end with at least 20 returns)."""
    values = []
    for end, t in enumerate(pairs.times):
        start = bisect_left(pairs.times, t - window_ms + 1)
        if end + 1 - start >= 20:
            corr = _corr_beta(pairs.btc[start:end + 1], pairs.xmr[start:end + 1])[0]
            if corr is not None:
                values.append(corr)
    if not values:
        return {"windows": 0, "min": None, "p10": None, "median": None, "p90": None, "max": None}
    values.sort()

    def q(share: float) -> float:
        return values[min(len(values) - 1, int(share * len(values)))]

    return {"windows": len(values), "min": values[0], "p10": q(0.10), "median": q(0.50), "p90": q(0.90), "max": values[-1]}


# ---------------------------------------------------------------- Kraken cross-check


def parse_kraken_ohlcvt(text: str) -> dict[int, float]:
    """Close by open time (ms) from a Kraken OHLCVT CSV (``time`` in Unix seconds, no header)."""
    out: dict[int, float] = {}
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0].strip().isdigit():
            continue
        if len(row) < 5:
            raise ValueError("Kraken OHLCVT row has fewer than 5 columns")
        stamp = int(row[0]) * 1000
        close = float(row[4])
        if close > 0 and stamp < HOLDOUT_START_MS:
            out[stamp] = close
    return out


def kraken_check(btc_1d: Mapping[int, float], xmr_1d: Mapping[int, float], kraken_xmr_btc: Mapping[int, float]) -> dict[str, object]:
    """Binance XMRUSDT/BTCUSDT against Kraken XMR/XBT on the same UTC days: level gap and return correlation."""
    days = sorted(set(btc_1d) & set(xmr_1d) & set(kraken_xmr_btc))
    if not days:
        return {"days": 0}
    gaps = sorted(abs((xmr_1d[d] / btc_1d[d]) / kraken_xmr_btc[d] - 1) for d in days)
    binance_ratio = {d: xmr_1d[d] / btc_1d[d] for d in days}
    pairs = aligned_returns(binance_ratio, dict(kraken_xmr_btc), INTERVAL_MS["1d"])
    return {"days": len(days), "first": _day(days[0]), "last": _day(days[-1]),
            "median_gap": gaps[len(gaps) // 2], "p95_gap": gaps[min(len(gaps) - 1, int(0.95 * len(gaps)))],
            "return_corr": _corr_beta(pairs.btc, pairs.xmr)[0]}


# ---------------------------------------------------------------- report


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def run(cache: Path | None, fetch: Fetcher = http_fetch, kraken_text: str | None = None,
        span: Sequence[tuple[int, int]] | None = None) -> dict[str, object]:
    report: dict[str, object] = {"version": VERSION, "source": "Binance USD-M monthly klines (data.binance.vision), checksums verified",
                                 "holdout_from": "2025-01-01", "intervals": {}, "missing_months": {}}
    daily: dict[str, dict[int, float]] = {}
    for interval in INTERVALS:
        closes = {}
        for symbol in SYMBOLS:
            closes[symbol], missing = load_closes(symbol, interval, cache, fetch, span)
            if missing:
                report["missing_months"][f"{symbol} {interval}"] = missing  # type: ignore[index]
        if interval == "1d":
            daily = closes
        step = INTERVAL_MS[interval]
        pairs = aligned_returns(closes["BTCUSDT"], closes["XMRUSDT"], step)
        entry = coupling(pairs, step)
        entry["by_year"] = by_year(pairs)
        if pairs.times:
            entry["first"], entry["last"] = _day(pairs.times[0]), _day(pairs.times[-1])
        if interval == "1d":
            entry["rolling_30d"] = rolling_corr(pairs, ROLLING_DAYS * step)
        report["intervals"][interval] = entry  # type: ignore[index]
    if kraken_text is not None:
        report["kraken_xmr_btc"] = kraken_check(daily.get("BTCUSDT", {}), daily.get("XMRUSDT", {}), parse_kraken_ohlcvt(kraken_text))
    return report


def _n(value: object, digits: int = 2) -> str:
    if value is None:
        return "–"
    return f"{float(value):.{digits}f}".replace(".", ",")  # type: ignore[arg-type]


def _pct(value: object) -> str:
    return "–" if value is None else f"{float(value) * 100:.1f} %".replace(".", ",")  # type: ignore[arg-type]


def markdown(report: Mapping[str, object]) -> str:
    """German report for Barti and Uzi."""
    lines = [f"# XMR und BTC: wie stark hängt Monero an Bitcoin? ({report['version']})", "",
             "Nur Beschreibung, keine Regel. Daten: Binance USD-M (XMRUSDT- und BTCUSDT-Perp), Monatsarchive mit Prüfsumme; "
             "nur 2020–2024, der Holdout ab 2025 bleibt zu.", "",
             "| Zeitrahmen | Paare | Zeitraum | Gleichlauf | Hebel (Beta) | BTC erklärt | eigene Bewegung | Gleichlauf bei BTC-Crash | übrige Kerzen |",
             "|---|---|---|---|---|---|---|---|---|"]
    intervals: Mapping[str, Mapping[str, object]] = report["intervals"]  # type: ignore[assignment]
    for interval, e in intervals.items():
        lines.append(f"| {interval} | {e['n']} | {e.get('first', '–')} bis {e.get('last', '–')} | {_n(e['corr'])} | {_n(e['beta'])} | "
                     f"{_pct(e['r2'])} | {_pct(e['own_share'])} | {_n(e.get('corr_crash'))} | {_n(e.get('corr_rest'))} |")
    lines += ["", "Gleichlauf = Korrelation der Renditen (1 = immer gleich, 0 = kein Zusammenhang). Hebel = wie viel % XMR "
              "im Schnitt macht, wenn BTC 1 % macht. BTC-Crash = die 10 % schlechtesten BTC-Kerzen.", "",
              "## Wer bewegt sich zuerst?", "",
              "Gleichlauf von XMR jetzt mit BTC k Kerzen vorher (k > 0: BTC zuerst, k < 0: XMR zuerst).", "",
              "| Zeitrahmen | " + " | ".join(f"k={k}" for k in LAGS) + " |", "|---|" + "---|" * len(LAGS)]
    for interval, e in intervals.items():
        ll: Mapping[str, object] = e["lead_lag"]  # type: ignore[assignment]
        lines.append(f"| {interval} | " + " | ".join(_n(ll.get(str(k))) for k in LAGS) + " |")
    lines += ["", "## Je Jahr (1h)", "", "| Jahr | Paare | Gleichlauf | Hebel |", "|---|---|---|---|"]
    for year, y in (intervals.get("1h") or {}).get("by_year", {}).items():  # type: ignore[union-attr]
        lines.append(f"| {year} | {y['n']} | {_n(y['corr'])} | {_n(y['beta'])} |")
    rolling = (intervals.get("1d") or {}).get("rolling_30d")  # type: ignore[union-attr]
    if rolling:
        lines += ["", "## Wie stabil ist der Gleichlauf? (30 Tage rollierend, Tageskerzen)", "",
                  f"{rolling['windows']} Fenster: kleinster Wert {_n(rolling['min'])}, 10 % liegen unter {_n(rolling['p10'])}, "
                  f"Mitte {_n(rolling['median'])}, 10 % liegen über {_n(rolling['p90'])}, größter Wert {_n(rolling['max'])}."]
    kraken = report.get("kraken_xmr_btc")
    if kraken:
        lines += ["", "## Gegenprobe Kraken XMR/BTC", ""]
        if kraken.get("days"):  # type: ignore[union-attr]
            lines.append(f"{kraken['days']} gemeinsame Tage ({kraken['first']} bis {kraken['last']}). Abstand Binance-Verhältnis zu Kraken: "  # type: ignore[index]
                         f"Mitte {_pct(kraken['median_gap'])}, 95 % unter {_pct(kraken['p95_gap'])}. "  # type: ignore[index]
                         f"Gleichlauf der Tagesrenditen {_n(kraken['return_corr'])}.")  # type: ignore[index]
        else:
            lines.append("Keine gemeinsamen Tage gefunden (Datei prüfen: Kraken OHLCVT, Tageskerzen, Paar XMR/XBT).")
    missing = report.get("missing_months") or {}
    if missing:
        lines += ["", "## Fehlende Monatsarchive", ""] + [f"- {key}: {', '.join(value)}" for key, value in missing.items()]  # type: ignore[union-attr]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Ordner für Archiv-Cache und Bericht")
    parser.add_argument("--kraken", type=Path, help="Kraken-OHLCVT-CSV XMR/XBT, Tageskerzen (z. B. XMRXBT_1440.csv)")
    args = parser.parse_args(argv)
    kraken_text = args.kraken.read_text(encoding="utf-8") if args.kraken else None
    report = run(args.out / "archive", kraken_text=kraken_text)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "xmr_btc_coupling.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (args.out / "xmr_btc_coupling.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
