"""S16: funding extremes as a contrarian signal, event study on the 24-h return distribution.

Rules: docs/research_lab/studien/S16_FUNDING_EXTREME_ALS_KONTRAINDIKATOR_VERTEILUNG_PRAEREGISTRIERUNG_ENTWURF.md
(version 1.0, sections 4.1, 5.1, 5.2, 6.1 to 6.4). Paper only; the holdout from 2025-01-01 is never loaded.

    python -m src.research_lab.studies.s16 count --root data/research_lab --out count.json
    python -m src.research_lab.studies.s16 evaluate --root data/research_lab --out result.json
"""
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.store import ArchiveStore, months
from src.research_lab.stats.inference import holm

SEED = 1616
DRAWS = 10_000
BLOCK_DAYS = 10
MIN_EVENTS = 500
MIN_EFFECT_PP = 0.1
ALPHA = 0.05
HOUR = 3_600_000
DAY = 24 * HOUR
WARMUP = 90 * DAY
SYMBOL_START = {"BTCUSDT": (2020, 1), "ETHUSDT": (2020, 1), "SOLUSDT": (2020, 10)}
END = (2024, 12)


def _ms(year: int, month: int, day: int = 1) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


SECTIONS = {"training": (0, _ms(2023, 1)), "validierung": (_ms(2023, 1), _ms(2025, 1))}
GROUPS = ("oben", "unten")
MEASURES = ("rendite_24h", "rueckschlag_max")


@dataclass(frozen=True)
class Term:
    symbol: str
    time: int  # funding time, floored to the minute
    section: str
    ret: float  # 24-h return
    dd: float  # maximum drawdown in the 24 h (<= 0)
    group: str | None  # "oben", "unten" or None

    @property
    def day(self) -> int:
        return self.time // DAY


def _section(time: int) -> str | None:
    return next((name for name, (lo, hi) in SECTIONS.items() if lo <= time < hi), None)


def build_terms(symbol: str, funding: Sequence[tuple[int, float]], candles: Mapping[int, tuple[float, float, float]]
                ) -> tuple[list[Term], int]:
    """All usable funding terms of one instrument and the number dropped for missing candles.

    funding: (time ms, rate) sorted by time. candles: open time -> (open, low, close) of 1h candles.
    """
    if not funding:
        return [], 0
    first = funding[0][0]
    terms, gaps = [], 0
    window: list[tuple[int, float]] = []
    lo = 0
    for index, (raw_time, rate) in enumerate(funding):
        time = raw_time - raw_time % 60_000
        # Past-only window (t - 90 d, t): earlier terms, never the value at t.
        while lo < index and funding[lo][0] <= raw_time - WARMUP:
            lo += 1
        if time < first + WARMUP:
            continue
        section = _section(time)
        start = -(-time // HOUR) * HOUR
        if section is None or _section(start + DAY - 1) != section:
            continue
        hours = [candles.get(start + h * HOUR) for h in range(24)]
        if any(h is None for h in hours):
            gaps += 1
            continue
        past = [r for _, r in funding[lo:index]]
        group = None
        if len(past) >= 10:
            cuts = statistics.quantiles(past, n=10, method="inclusive")
            group = "oben" if rate > cuts[-1] else "unten" if rate < cuts[0] else None
        entry = hours[0][0]
        ret = hours[-1][2] / entry - 1
        dd = min(h[1] for h in hours) / entry - 1
        terms.append(Term(symbol, time, section, ret, dd, group))
    return terms, gaps


def decluster(terms: Iterable[Term], group: str) -> list[Term]:
    """At most one event per 24 h per instrument and group: keep the first, then the next one >= 24 h later."""
    kept: list[Term] = []
    last: dict[str, int] = {}
    for term in sorted((t for t in terms if t.group == group), key=lambda t: (t.symbol, t.time)):
        if term.time >= last.get(term.symbol, -DAY):
            kept.append(term)
            last[term.symbol] = term.time + DAY
    return kept


def design_effect(values: Sequence[float], clusters: Sequence[int]) -> float:
    """Variance of the mean from day clusters divided by s^2 / n, at least 1."""
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
    clustered = sum(v * v for v in sums.values()) / n ** 2
    return max(1.0, clustered / (s2 / n))


def _value(term: Term, measure: str) -> float:
    return term.ret if measure == "rendite_24h" else term.dd


def _deltas(all_terms: Sequence[Term], events: Mapping[str, Sequence[Term]]) -> dict[str, float]:
    base = {m: statistics.median(_value(t, m) for t in all_terms) for m in MEASURES}
    return {f"{g}/{m}": (statistics.median(_value(t, m) for t in events[g]) - base[m]) * 100
            for g in events for m in MEASURES}


def bootstrap(all_terms: Sequence[Term], events: Mapping[str, Sequence[Term]], *, draws: int = DRAWS,
              seed: int = SEED) -> dict[str, dict]:
    """Moving-block bootstrap over UTC days (all instruments together); delta in percentage points."""
    observed = _deltas(all_terms, events)
    first, last = min(t.day for t in all_terms), max(t.day for t in all_terms)
    days = list(range(first, last + 1))
    by_day_all: dict[int, list[Term]] = {}
    for t in all_terms:
        by_day_all.setdefault(t.day, []).append(t)
    by_day_ev = {g: {} for g in events}
    for g, terms in events.items():
        for t in terms:
            by_day_ev[g].setdefault(t.day, []).append(t)
    rng = random.Random(seed)
    n_blocks = math.ceil(len(days) / BLOCK_DAYS)
    starts_max = len(days) - BLOCK_DAYS
    samples: dict[str, list[float]] = {k: [] for k in observed}
    for _ in range(draws):
        picked = [days[s + i] for s in (rng.randint(0, starts_max) for _ in range(n_blocks)) for i in range(BLOCK_DAYS)]
        all_s = [t for d in picked for t in by_day_all.get(d, ())]
        ev_s = {g: [t for d in picked for t in by_day_ev[g].get(d, ())] for g in events}
        if any(not v for v in ev_s.values()):
            raise ValueError("bootstrap draw without events")
        for key, value in _deltas(all_s, ev_s).items():
            samples[key].append(value)
    result = {}
    for key, delta in observed.items():
        values = sorted(samples[key])
        below = sum(1 for v in values if v <= 0)
        above = sum(1 for v in values if v >= 0)
        p = min(1.0, 2 * (1 + min(below, above)) / (1 + draws))
        result[key] = {"delta_pp": delta, "ci95_pp": [values[int(0.025 * draws)], values[int(0.975 * draws) - 1]], "p": p}
    return result


def load(root: Path) -> tuple[dict[str, list[Term]], dict[str, int], str]:
    store = ArchiveStore(root)
    terms, gaps, refs_all = {}, {}, []
    for symbol, start in SYMBOL_START.items():
        span = months(start, END)
        f_refs = [ArchiveRef(Market.USDM, Dataset.FUNDING, y, m, symbol=symbol) for y, m in span]
        k_refs = [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, interval="1h", symbol=symbol) for y, m in span]
        refs_all += f_refs + k_refs
        funding = [(f.time, f.rate) for f in store.load_funding(f_refs)]
        candles = {k.open_time: (k.open, k.low, k.close) for k in store.load_klines(k_refs)}
        terms[symbol], gaps[symbol] = build_terms(symbol, funding, candles)
    return terms, gaps, store.dataset_hash(refs_all)


def count(terms: Mapping[str, list[Term]], gaps: Mapping[str, int]) -> dict:
    """Event counts only, no returns (count run, section 5.2)."""
    flat = [t for ts in terms.values() for t in ts]
    out: dict = {"terms": {s: {sec: sum(1 for t in ts if t.section == sec) for sec in SECTIONS} for s, ts in terms.items()},
                 "gaps_missing_candles": dict(gaps), "events": {}}
    for g in GROUPS:
        kept = decluster(flat, g)
        raw = sum(1 for t in flat if t.group == g)
        out["events"][g] = {
            "roh": raw, "entclustert": len(kept),
            "je_instrument_abschnitt": {s: {sec: sum(1 for t in kept if t.symbol == s and t.section == sec) for sec in SECTIONS}
                                        for s in terms},
            "je_abschnitt": {sec: sum(1 for t in kept if t.section == sec) for sec in SECTIONS},
            "pruefbar": len(kept) >= MIN_EVENTS,
        }
    return out


def evaluate(terms: Mapping[str, list[Term]], counted: Mapping) -> dict:
    flat = [t for ts in terms.values() for t in ts]
    testable = [g for g in GROUPS if counted["events"][g]["pruefbar"]]
    if not testable:
        return {"urteil": "nicht prüfbar", "abschnitte": {}}
    sections = {}
    for sec in SECTIONS:
        all_terms = [t for t in flat if t.section == sec]
        events = {g: [t for t in decluster(flat, g) if t.section == sec] for g in testable}
        stats = bootstrap(all_terms, events)
        significant = holm({k: v["p"] for k, v in stats.items()}, m=len(stats), alpha=ALPHA)
        for key, item in stats.items():
            item["holm_signifikant"] = key in significant
        neff = {}
        for g, evs in events.items():
            neff[g] = {}
            for m in MEASURES:
                d = design_effect([_value(t, m) for t in evs], [t.day for t in evs])
                neff[g][m] = {"n": len(evs), "D": d, "n_eff": math.floor(len(evs) / d)}
        sections[sec] = {"n_gesamt": len(all_terms), "vergleiche": stats, "n_eff": neff}
    passed = []
    for key in sections["training"]["vergleiche"]:
        a, b = sections["training"]["vergleiche"][key], sections["validierung"]["vergleiche"][key]
        if (a["holm_signifikant"] and b["holm_signifikant"] and abs(a["delta_pp"]) >= MIN_EFFECT_PP
                and abs(b["delta_pp"]) >= MIN_EFFECT_PP and a["delta_pp"] * b["delta_pp"] > 0):
            passed.append(key)
    return {"urteil": "BESTANDEN" if passed else "NICHT BESTANDEN", "bestandene_vergleiche": passed,
            "pruefbare_gruppen": testable, "abschnitte": sections}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s16")
    parser.add_argument("step", choices=("count", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    terms, gaps, digest = load(args.root)
    counted = count(terms, gaps)
    result = {"studie": "S16", "version": "1.0", "seed": SEED, "datensatz_sha256": digest, "zaehllauf": counted}
    if args.step == "evaluate":
        result["auswertung"] = evaluate(terms, counted)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "auswertung"} | (
        {"urteil": result["auswertung"]["urteil"]} if "auswertung" in result else {}), ensure_ascii=False)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
