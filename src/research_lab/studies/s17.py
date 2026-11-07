"""S17: costs in R by time of day (BTCUSDT spot, S8 minute bars).

Rules: docs/research_lab/studien/S17_KOSTEN_IN_R_NACH_TAGESZEIT_PRAEREGISTRIERUNG_ENTWURF.md
(version 1.0, sections 4.1, 5.1, 5.2, 6.1 to 6.5). Paper only; the holdout from 2025-01-01 is never loaded.

    python -m src.research_lab.studies.s17 count    --bars <orderflow_ml root> --out count.json
    python -m src.research_lab.studies.s17 train    --bars <root> --out train.json   # freezes the groups
    python -m src.research_lab.studies.s17 validate --bars <root> --frozen train.json --out validate.json
    python -m src.research_lab.studies.s17 describe --bars <root> --klines <research_lab root> --frozen train.json --validated validate.json --out describe.json

``describe`` also computes the year-pair stability (section 6.1) and the verdict (section 6.3).

``train`` reads only days up to 2022-12-31. ``validate`` reads days from 2022-12-31 on (the day before the
section only feeds the ATR lead hours) and takes the hour and weekday groups from the frozen training file.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.research_lab.protocol import BASE_COSTS, HOLDOUT_START_MS, STRESS_COSTS
from src.research_lab.stats.inference import holm

SEED = 1717
DRAWS = 10_000
ATR_N = 14
ATR_FACTOR = 1.5  # S7b, src/research_lab/hypotheses/s7.py
MIN_STOP_DISTANCE = 0.01  # S7b, descriptive variant only
MIN_SECTION = 5000
MIN_CELL = 100
MIN_EFFECT_R = 0.05
MIN_SPEARMAN = 0.5
GROUP_SIZE = 6
ALPHA = 0.05
HOUR = 3_600_000
DAY = 24 * HOUR
WEEK = 7 * DAY
MONDAY_OFFSET = 4 * DAY  # 1970-01-01 is a Thursday; 1970-01-05 00:00 UTC is a Monday
FIRST_DAY = date(2020, 1, 1)
LAST_DAY = date(2024, 12, 31)
ROUND_TRIP = 2 * (BASE_COSTS.fee + BASE_COSTS.slippage)  # 0.16 %
ROUND_TRIP_STOP = BASE_COSTS.fee + BASE_COSTS.slippage + BASE_COSTS.fee + BASE_COSTS.stop_slippage  # 0.18 %
ROUND_TRIP_STRESS = 2 * (STRESS_COSTS.fee + STRESS_COSTS.slippage)  # 0.32 %
BAR_COLUMNS = ("window_start_ms", "trade_count", "buy_quote_e8", "sell_quote_e8", "first_price_e8",
               "last_price_e8", "high_price_e8", "low_price_e8")
WEEKDAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)


SECTIONS = {"training": (_ms(FIRST_DAY), _ms(date(2023, 1, 1))), "validierung": (_ms(date(2023, 1, 1)), _ms(date(2025, 1, 1)))}
YEARS = tuple(range(2020, 2025))


def section_of(time: int) -> str | None:
    return next((name for name, (lo, hi) in SECTIONS.items() if lo <= time < hi), None)


def week_of(time: int) -> int:
    """Calendar week index, Monday 00:00 UTC to Sunday 24:00 UTC."""
    return (time - MONDAY_OFFSET) // WEEK


def weekday_of(time: int) -> int:
    return ((time // DAY) + 3) % 7  # 0 = Monday


def year_of(time: int) -> int:
    return datetime.fromtimestamp(time / 1000, tz=timezone.utc).year


# -- input -------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Candle:
    """One UTC hour aggregated from minute bars; prices in USDT. ``trades`` False means no minute with a trade."""

    start: int
    trades: bool
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    trade_count: int = 0
    buy_quote: int = 0
    sell_quote: int = 0
    minute_vol: float | None = None  # sample std of 1-minute ln returns within the hour
    faulty: bool = False  # the day's reduction report shows id gaps, time regressions or duplicates


def hour_candle(start: int, minutes: Sequence[Sequence[int]], *, faulty: bool = False) -> Candle:
    """Aggregate the 60 minute rows (BAR_COLUMNS order) of one hour."""
    traded = [m for m in minutes if m[1] > 0]
    if not traded:
        return Candle(start, False, faulty=faulty)
    rets = [math.log(b[5] / a[5]) for a, b in zip(minutes, minutes[1:]) if a[1] > 0 and b[1] > 0]
    vol = statistics.stdev(rets) if len(rets) >= 2 else None
    return Candle(start, True, traded[0][4] / 1e8, max(m[6] for m in traded) / 1e8, min(m[7] for m in traded) / 1e8,
                  traded[-1][5] / 1e8, sum(m[1] for m in traded), sum(m[2] for m in traded), sum(m[3] for m in traded),
                  vol, faulty)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_candles(root: Path, first: date, last: date) -> tuple[dict[int, Candle], str]:
    """Hour candles from the S8 day files ``bars/BTCUSDT-<day>.csv``, each checked against the bar manifest."""
    if _ms(last) + DAY > HOLDOUT_START_MS or last > LAST_DAY:
        raise PermissionError("S17 reads no holdout day")
    manifest = json.loads((root / "bars_manifest.json").read_text())
    candles: dict[int, Candle] = {}
    entries = []
    day = first
    while day <= last:
        key = day.isoformat()
        entry = manifest.get(key)
        path = root / "bars" / f"BTCUSDT-{key}.csv"
        if entry is None or not path.exists():
            raise FileNotFoundError(f"{key}: minute bars missing")
        if _sha256(path) != entry["bars_sha256"]:
            raise ValueError(f"{key}: bar file changed on disk since it was verified")
        quality = entry["quality"]
        faulty = bool(quality["id_gaps"] or quality["time_regressions"] or quality["duplicate_rows"])
        with path.open(newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            index = [header.index(c) for c in BAR_COLUMNS]
            rows = [[int(row[i]) for i in index] for row in reader]
        start = _ms(day)
        if len(rows) != 1440 or any(r[0] != start + i * 60_000 for i, r in enumerate(rows)):
            raise ValueError(f"{key}: bar file is not one full day")
        for h in range(24):
            candles[start + h * HOUR] = hour_candle(start + h * HOUR, rows[h * 60:(h + 1) * 60], faulty=faulty)
        entries.append((key, entry))
        day += timedelta(days=1)
    return candles, hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest()


# -- cases ---------------------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Case:
    start: int
    section: str
    cost_r: float  # main measure: 0.16 % x open / (1.5 x ATR14 on 1h), no minimum distance
    atr_rel: float  # ATR / open

    @property
    def hour(self) -> int:
        return (self.start // HOUR) % 24

    @property
    def weekday(self) -> int:
        return weekday_of(self.start)

    @property
    def week(self) -> int:
        return week_of(self.start)

    @property
    def day(self) -> int:
        return self.start // DAY

    @property
    def year(self) -> int:
        return year_of(self.start)


def true_ranges(candles: Sequence[Candle]) -> list[float]:
    """True range of each candle after the first, as in backtest.indicators.atr."""
    return [max(b.high - b.low, abs(b.high - a.close), abs(b.low - a.close)) for a, b in zip(candles, candles[1:])]


def atr_before(candles: Mapping[int, Candle], start: int, step: int = HOUR, n: int = ATR_N) -> float | None:
    """ATR(n) from the n + 1 closed candles before ``start`` (simple mean, no Wilder smoothing); None if one is missing."""
    history = [candles.get(start - k * step) for k in range(n + 1, 0, -1)]
    if any(c is None or not c.trades or c.faulty for c in history):
        return None
    return sum(true_ranges(history)) / n  # type: ignore[arg-type]


def classify(candles: Mapping[int, Candle], start: int) -> str:
    """Exclusion reason of the case at ``start`` or "gueltig"."""
    own = candles.get(start)
    if own is None or not own.trades:
        return "stunde_ohne_handel"
    lead = [candles.get(start - k * HOUR) for k in range(1, ATR_N + 2)]
    if any(c is not None and c.faulty for c in [own, *lead]):
        return "fehlerhafte_minute"
    if any(c is None or not c.trades for c in lead):
        return "vorlauf_unvollstaendig"
    return "gueltig"


def build_cases(candles: Mapping[int, Candle], lo: int, hi: int) -> tuple[list[Case], dict[str, int]]:
    """All valid cases with start in [lo, hi) and the exclusion counts by reason."""
    cases, excluded = [], {"stunde_ohne_handel": 0, "vorlauf_unvollstaendig": 0, "fehlerhafte_minute": 0}
    for start in range(lo, hi, HOUR):
        reason = classify(candles, start)
        if reason != "gueltig":
            excluded[reason] += 1
            continue
        atr = atr_before(candles, start)
        own = candles[start]
        if not atr:
            excluded["vorlauf_unvollstaendig"] += 1
            continue
        cases.append(Case(start, section_of(start) or "", ROUND_TRIP * own.open / (ATR_FACTOR * atr), atr / own.open))
    return cases, excluded


# -- statistics ------------------------------------------------------------------------------------
def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    def ranks(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out
    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else 0.0


def pick_groups(medians: Mapping[int, float], size: int = GROUP_SIZE) -> tuple[list[int], list[int]]:
    """Cheapest and dearest ``size`` keys by median; ties go to the smaller key first."""
    cheap = sorted(medians, key=lambda k: (medians[k], k))[:size]
    dear = sorted(medians, key=lambda k: (-medians[k], k))[:size]
    return sorted(cheap), sorted(dear)


def design_effect(values: Sequence[float], clusters: Sequence[int]) -> float:
    """Variance of the mean from day clusters divided by s^2 / n, at least 1 (PROTOKOLL.md 1.3, A3)."""
    n = len(values)
    if n < 2:
        return 1.0
    mean = sum(values) / n
    s2 = sum((x - mean) ** 2 for x in values) / (n - 1)
    if s2 == 0:
        return 1.0
    sums: dict[int, float] = {}
    for x, c in zip(values, clusters):
        sums[c] = sums.get(c, 0.0) + (x - mean)
    return max(1.0, sum(v * v for v in sums.values()) / n ** 2 / (s2 / n))


def p_two_sided(samples: Sequence[float], draws: int) -> float:
    below = sum(1 for v in samples if v <= 0)
    above = sum(1 for v in samples if v >= 0)
    return min(1.0, 2 * (1 + min(below, above)) / (1 + draws))


def week_bootstrap(cases: Sequence[Case], comparisons: Mapping[str, tuple[Sequence[int], Sequence[int], str]], *,
                   draws: int = DRAWS, seed: int = SEED) -> dict[str, dict]:
    """Block bootstrap over calendar weeks. comparisons: name -> (cheap keys, dear keys, "hour" or "weekday").

    Delta = median(dear) - median(cheap) in R; both medians are recomputed in every draw.
    """
    weeks: dict[int, list[Case]] = {}
    for c in cases:
        weeks.setdefault(c.week, []).append(c)
    keys = sorted(weeks)
    per_week = {name: {w: ([c.cost_r for c in weeks[w] if getattr(c, attr) in cheap],
                           [c.cost_r for c in weeks[w] if getattr(c, attr) in dear]) for w in keys}
                for name, (cheap, dear, attr) in comparisons.items()}
    observed = {}
    for name, rows in per_week.items():
        observed[name] = (statistics.median(v for w in keys for v in rows[w][1])
                          - statistics.median(v for w in keys for v in rows[w][0]))
    rng = random.Random(seed)
    samples: dict[str, list[float]] = {name: [] for name in comparisons}
    for _ in range(draws):
        picked = [keys[rng.randrange(len(keys))] for _ in keys]
        for name, rows in per_week.items():
            cheap = [v for w in picked for v in rows[w][0]]
            dear = [v for w in picked for v in rows[w][1]]
            samples[name].append(statistics.median(dear) - statistics.median(cheap))
    out = {}
    for name, delta in observed.items():
        values = sorted(samples[name])
        out[name] = {"delta_r": delta, "ci95_r": [values[int(0.025 * draws)], values[int(0.975 * draws) - 1]],
                     "p": p_two_sided(values, draws), "wochen": len(keys)}
    return out


def cell_bootstrap(cases: Sequence[Case], *, draws: int = DRAWS, seed: int = SEED) -> dict[str, dict]:
    """Median and week-bootstrap 95 % interval per cell (hour x weekday), descriptive only."""
    weeks: dict[int, dict[tuple[int, int], float]] = {}
    for c in cases:
        weeks.setdefault(c.week, {})[(c.hour, c.weekday)] = c.cost_r
    keys = sorted(weeks)
    cells = sorted({(c.hour, c.weekday) for c in cases})
    rng = random.Random(seed + 1)
    samples: dict[tuple[int, int], list[float]] = {cell: [] for cell in cells}
    for _ in range(draws):
        picked = [weeks[keys[rng.randrange(len(keys))]] for _ in keys]
        for cell in cells:
            values = [row[cell] for row in picked if cell in row]
            if values:
                samples[cell].append(statistics.median(values))
    out = {}
    for cell in cells:
        values = sorted(samples[cell])
        n = len(values)
        observed = [row[cell] for row in weeks.values() if cell in row]
        out[f"{cell[0]:02d}h/{WEEKDAYS[cell[1]]}"] = {"n": len(observed), "median_r": statistics.median(observed),
                                                      "ci95_r": [values[int(0.025 * n)], values[int(0.975 * n) - 1]]}
    return out


def medians_by(cases: Iterable[Case], attr: str) -> dict[int, float]:
    groups: dict[int, list[float]] = {}
    for c in cases:
        groups.setdefault(getattr(c, attr), []).append(c.cost_r)
    return {k: statistics.median(v) for k, v in sorted(groups.items())}


def spec_digest(text: str) -> str:
    """SHA-256 of the study's rules: from "## 1." up to (not including) "## Änderungsprotokoll", UTF-8."""
    start = text.index("\n## 1. ") + 1
    body = text[start:text.index("\n## Änderungsprotokoll\n", start) + 1]
    if not body.strip():
        raise ValueError("no rules text found")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


# -- steps -------------------------------------------------------------------------------------------
def count(cases: Sequence[Case], excluded: Mapping[str, Mapping[str, int]]) -> dict:
    """Case counts only, no costs (count run, section 5.2)."""
    out = {}
    for sec in SECTIONS:
        own = [c for c in cases if c.section == sec]
        cells: dict[str, int] = {}
        for c in own:
            key = f"{c.hour:02d}h/{WEEKDAYS[c.weekday]}"
            cells[key] = cells.get(key, 0) + 1
        smallest = min(cells.items(), key=lambda kv: (kv[1], kv[0])) if cells else ("-", 0)
        out[sec] = {"faelle": len(own), "ausschluesse": dict(excluded[sec]), "zellen": len(cells),
                    "kleinste_zelle": {"zelle": smallest[0], "n": smallest[1]},
                    "zellen_unter_min": sorted(k for k, v in cells.items() if v < MIN_CELL),
                    "pruefbar": len(own) >= MIN_SECTION, "zellen_je": cells}
    return out


def section_test(cases: Sequence[Case], hours: tuple[Sequence[int], Sequence[int]],
                 days: tuple[Sequence[int], Sequence[int]]) -> dict:
    stats = week_bootstrap(cases, {"stunden": (hours[0], hours[1], "hour"), "wochentag": (days[0], days[1], "weekday")})
    significant = holm({k: v["p"] for k, v in stats.items()}, m=2, alpha=ALPHA)
    for key, item in stats.items():
        item["holm_signifikant"] = key in significant
    neff = {}
    for name, keys in (("G", hours[0]), ("T", hours[1])):
        own = [c for c in cases if c.hour in keys]
        d = design_effect([c.cost_r for c in own], [c.day for c in own])
        neff[name] = {"n": len(own), "D": d, "n_eff": math.floor(len(own) / d)}
    return {"n": len(cases), "vergleiche": stats, "n_eff": neff,
            "median_je_stunde": medians_by(cases, "hour"), "median_je_wochentag": medians_by(cases, "weekday")}


def train(cases: Sequence[Case], counted: Mapping) -> dict:
    own = [c for c in cases if c.section == "training"]
    if not counted["training"]["pruefbar"]:
        return {"urteil_abschnitt": "nicht prüfbar"}
    hours = pick_groups(medians_by(own, "hour"))
    days = pick_groups(medians_by(own, "weekday"), size=1)
    result = section_test(own, hours, days)
    result["eingefroren"] = {"G_stunden": hours[0], "T_stunden": hours[1], "guenstigster_wochentag": days[0][0],
                             "teuerster_wochentag": days[1][0]}
    return result


def validate(cases: Sequence[Case], counted: Mapping, frozen: Mapping) -> dict:
    own = [c for c in cases if c.section == "validierung"]
    if not counted["validierung"]["pruefbar"]:
        return {"urteil_abschnitt": "nicht prüfbar"}
    f = frozen["eingefroren"]
    return section_test(own, (f["G_stunden"], f["T_stunden"]), ([f["guenstigster_wochentag"]], [f["teuerster_wochentag"]]))


def stability(cases: Sequence[Case]) -> dict:
    by_year = {y: medians_by((c for c in cases if c.year == y), "hour") for y in YEARS}
    out = {}
    for a, b in zip(YEARS, YEARS[1:]):
        hours = sorted(set(by_year[a]) & set(by_year[b]))
        out[f"{a}->{b}"] = spearman([by_year[a][h] for h in hours], [by_year[b][h] for h in hours]) if len(hours) >= 2 else None
    return {"rho": out, "erfuellt": all(v is not None and v >= MIN_SPEARMAN for v in out.values())}


def verdict(counted: Mapping, training: Mapping, validation: Mapping, stable: Mapping) -> dict:
    if not (counted["training"]["pruefbar"] and counted["validierung"]["pruefbar"]):
        return {"urteil": "NICHT PRÜFBAR"}
    a, b = training["vergleiche"]["stunden"], validation["vergleiche"]["stunden"]
    conditions = {"1_holm_beide": a["holm_signifikant"] and b["holm_signifikant"],
                  "2_effekt_beide": a["delta_r"] >= MIN_EFFECT_R and b["delta_r"] >= MIN_EFFECT_R,
                  "3_stabilitaet": stable["erfuellt"]}
    return {"urteil": "BESTANDEN" if all(conditions.values()) else "NICHT BESTANDEN", "bedingungen": conditions}


def describe(candles: Mapping[int, Candle], cases: Sequence[Case], frozen: Mapping, klines_root: Path | None) -> dict:
    """Descriptive results only (sections 5.1 and 6.2); none of them enters the verdict."""
    out: dict = {}
    for sec in SECTIONS:
        own = [c for c in cases if c.section == sec]
        hourly: dict[int, dict] = {}
        for h in range(24):
            hc = [c for c in own if c.hour == h]
            cands = [candles[c.start] for c in hc]
            atr4 = [atr_before(candles_4h(candles), c.start - c.start % (4 * HOUR), 4 * HOUR) for c in hc]
            cost4 = [ROUND_TRIP * candles[c.start].open / (ATR_FACTOR * a) for c, a in zip(hc, atr4) if a]
            floor = [ROUND_TRIP / max(ATR_FACTOR * c.atr_rel, MIN_STOP_DISTANCE) for c in hc]
            vols = [x.minute_vol for x in cands if x.minute_vol is not None]
            hourly[h] = {
                "n": len(hc), "median_r": statistics.median(c.cost_r for c in hc),
                "median_r_stopfall_018": statistics.median(c.cost_r * ROUND_TRIP_STOP / ROUND_TRIP for c in hc),
                "median_r_stress_032": statistics.median(c.cost_r * ROUND_TRIP_STRESS / ROUND_TRIP for c in hc),
                "median_r_atr4h": statistics.median(cost4) if cost4 else None, "n_atr4h": len(cost4),
                "median_r_mit_mindestabstand": statistics.median(floor),
                "anteil_mindestabstand_greift": sum(1 for c in hc if ATR_FACTOR * c.atr_rel < MIN_STOP_DISTANCE) / len(hc),
                "median_kaufanteil": statistics.median(x.buy_quote / (x.buy_quote + x.sell_quote) for x in cands
                                                       if x.buy_quote + x.sell_quote),
                "median_handelszahl": statistics.median(x.trade_count for x in cands),
                "median_minutenvol": statistics.median(vols) if vols else None,
            }
        g, t = frozen["eingefroren"]["G_stunden"], frozen["eingefroren"]["T_stunden"]

        def delta(field: str) -> float | None:
            tv = [hourly[h][field] for h in t]
            gv = [hourly[h][field] for h in g]
            if None in tv or None in gv:
                return None
            return statistics.fmean(tv) - statistics.fmean(gv)
        out[sec] = {
            "je_stunde": hourly,
            "anteil_stunden_median_unter_025r": sum(1 for v in hourly.values() if v["median_r"] < 0.25) / 24,
            "differenz_mittel_der_stundenmediane_T_minus_G": {f: delta(f) for f in (
                "median_r", "median_r_atr4h", "median_r_mit_mindestabstand")},
            "zellen": cell_bootstrap(own),
        }
    if klines_root is not None:
        out["gegenprobe_spot_klines_1h"] = kline_check(candles, klines_root)
    return out


_4H_CACHE: dict[int, dict[int, Candle]] = {}


def candles_4h(candles: Mapping[int, Candle]) -> dict[int, Candle]:
    """4h blocks from 00:00 UTC built from the hour candles; a block is missing if one hour has no trade."""
    key = id(candles)
    if key in _4H_CACHE:
        return _4H_CACHE[key]
    blocks: dict[int, Candle] = {}
    for start in sorted(s for s in candles if s % (4 * HOUR) == 0):
        hours = [candles.get(start + k * HOUR) for k in range(4)]
        if any(h is None for h in hours):
            continue
        traded = [h for h in hours if h.trades]  # type: ignore[union-attr]
        faulty = any(h.faulty for h in hours)  # type: ignore[union-attr]
        if len(traded) < 4:
            blocks[start] = Candle(start, False, faulty=faulty)
            continue
        blocks[start] = Candle(start, True, traded[0].open, max(h.high for h in traded), min(h.low for h in traded),
                               traded[-1].close, faulty=faulty)
    _4H_CACHE[key] = blocks
    return blocks


def kline_check(candles: Mapping[int, Candle], root: Path) -> dict:
    from src.research_lab.data.archive import ArchiveRef, Dataset, Market
    from src.research_lab.data.store import ArchiveStore, months
    store = ArchiveStore(root)
    first = datetime.fromtimestamp(min(candles) / 1000, tz=timezone.utc)
    last = datetime.fromtimestamp(max(candles) / 1000, tz=timezone.utc)
    refs = [ArchiveRef(Market.SPOT, Dataset.KLINES, y, m, interval="1h", symbol="BTCUSDT")
            for y, m in months((first.year, first.month), (last.year, last.month))]
    devs = {"open": [], "high": [], "low": [], "close": []}
    compared = 0
    for k in store.load_klines(refs):
        c = candles.get(k.open_time)
        if c is None or not c.trades:
            continue
        compared += 1
        for f in devs:
            devs[f].append(abs(getattr(c, f) / getattr(k, f) - 1))
    return {"stunden_verglichen": compared, "datensatz_sha256": store.dataset_hash(refs),
            **{f: {"median_rel": statistics.median(v), "max_rel": max(v), "anteil_exakt": sum(1 for x in v if x == 0) / len(v)}
               for f, v in devs.items() if v}}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s17")
    parser.add_argument("step", choices=("count", "train", "validate", "describe"))
    parser.add_argument("--bars", type=Path, required=True, help="S8 orderflow_ml root with bars/ and bars_manifest.json")
    parser.add_argument("--klines", type=Path, help="research_lab archive root with spot/klines/BTCUSDT/1h (describe only)")
    parser.add_argument("--frozen", type=Path, help="output of the train step")
    parser.add_argument("--validated", type=Path, help="output of the validate step (describe only)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    first = FIRST_DAY if args.step != "validate" else date(2022, 12, 31)
    last = LAST_DAY if args.step != "train" else date(2022, 12, 31)
    candles, digest = load_candles(args.bars, first, last)
    cases, excluded = [], {}
    for sec, (lo, hi) in SECTIONS.items():
        lo, hi = max(lo, _ms(first)), min(hi, _ms(last) + DAY)
        own, ex = build_cases(candles, lo, hi) if lo < hi else ([], {"stunde_ohne_handel": 0, "vorlauf_unvollstaendig": 0,
                                                                      "fehlerhafte_minute": 0})
        cases += own
        excluded[sec] = ex
    result: dict = {"studie": "S17", "version": "1.0", "schritt": args.step, "seed": SEED,
                    "gelesene_tage": [first.isoformat(), last.isoformat()], "datensatz_sha256": digest}
    counted = count(cases, excluded)
    if args.step == "count":
        result["zaehllauf"] = counted
    elif args.step == "train":
        result["zaehllauf_training"] = counted["training"]
        result["training"] = train(cases, counted)
        result["stabilitaet_2020_2022"] = stability(cases)
    else:
        frozen = json.loads(args.frozen.read_text())
        if args.step == "validate":
            result["zaehllauf_validierung"] = counted["validierung"]
            result["validierung"] = validate(cases, counted, frozen["training"])
        else:
            validated = json.loads(args.validated.read_text())
            result["zaehllauf"] = counted
            result["stabilitaet"] = stability(cases)
            result["entscheidung"] = verdict(counted, frozen["training"], validated["validierung"], result["stabilitaet"])
            result["beschreibend"] = describe(candles, cases, frozen["training"], args.klines)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
