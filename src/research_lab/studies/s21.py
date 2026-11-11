"""S21: does order flow or funding tell whether a broken swing level flips? (BTCUSDT, 1h, 2017-08 to 2024).

Rules: docs/research_lab/studien/S21_ORDERFLOW_FUNDING_AM_FLIP_PRAEREGISTRIERUNG_ENTWURF.md (version 0.1).
Observation study without trades and without a register slot; the holdout from 2025-01-01 is never loaded.

    python -m src.research_lab.studies.s21 count    --root data/research_lab --out DIR [--fetch] [--footprint S8_ROOT --fp-cache DIR]
    python -m src.research_lab.studies.s21 evaluate --root data/research_lab --out DIR [--footprint S8_ROOT --fp-cache DIR] [--workers N]

Events and the flip label are S20's, unchanged (``s20.find_events``, ``s20.label``; S20 is frozen as 1.0 and
failed). S21 asks a different question: does a source the candle does not hold add to the one thing that sorted
in S20, the distance of the close beyond the level (the mechanics model)? Three families, each tested alone
against the mechanics model, Holm over the three:

    K  candle order flow over the 10 candles before the break (2017-2024): CVD share, CVD-price co-movement, volume trend
    F  engine footprint flags in the hour before the break and the break hour (S8 store, 2020-2024)
    G  funding: last published rate and its z-score over 30 days (USD-M archive, 2020-2024)

``count`` is results-blind (events and coverage per family, no label). ``evaluate`` refuses to run while
``VERSION`` is a draft. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from bisect import bisect_right
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from src.research_lab.data.parse import Kline
from src.research_lab.stats.inference import holm
from src.research_lab.studies import s20
from src.research_lab.studies.s20 import HOUR, UP, Event

VERSION = "0.1"
SEED = 21
WINDOW = 10  # fixed: the window S20 chose inside its training data (S20 report, section 3); no new choice here
FP_START_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)  # S8 store and funding history
FAMILIES = ("K", "F", "G")
FAMILY_NAMES = {"K": "Kerzen-Orderflow", "F": "Footprint-Orderflow", "G": "Funding"}
FEATURES = {
    "K": ("cvd_anteil", "cvd_gleichlauf", "volumentrend"),
    "F": ("fp_I", "fp_A", "fp_C", "fp_T", "fp_H", "fp_E"),
    "G": ("funding_letzt", "funding_z"),
}
START_MS = {"K": 0, "F": FP_START_MS, "G": FP_START_MS}
MIN_EVENTS = {"K": {"training": 400, "validierung": 150}, "F": {"training": 250, "validierung": 150},
              "G": {"training": 250, "validierung": 150}}
MIN_REL_GAIN = 0.01
ALPHA = 0.05
HOLM_M = 3
BOOT_DRAWS = 9_999
SHIFT_DRAWS = 199
MIN_SHIFT = 100
FP_CANDLE_MS = 15 * 60_000
FP_CANDLES = 8
FP_FAMILIES = ("I", "A", "C", "T", "H", "E")
FUNDING_LOOKBACK = 90
FUNDING_FIRST_MONTH = (2020, 1)  # first month in the USD-M fundingRate archive (2019 answers 404)


# -- K: candle order flow -----------------------------------------------------------------------------


def _correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Pearson correlation; 0 when one side does not move. Below 0: flow and price diverge."""
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 1e-18 or syy <= 1e-18:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


def candle_flow(bars: Sequence[Kline], event: Event, n: int = WINDOW) -> tuple[float, float, float]:
    """CVD share in break direction, CVD-close correlation over window plus break candle, log-volume trend."""
    t = event.index
    span = bars[t - n:t + 1]
    window = bars[t - n:t]
    s = 1.0 if event.direction == UP else -1.0
    total = sum(b.volume for b in span)
    share = s * sum(b.delta for b in span) / total if total > 0 else 0.0
    path, running = [], 0.0
    for b in span:
        running += b.delta
        path.append(running)
    logs = [math.log(b.volume) if b.volume > 0 else 0.0 for b in window]
    half = n // 2
    trend = sum(logs[n - half:]) / half - sum(logs[:half]) / half
    return share, _correlation(path, [b.close for b in span]), trend


# -- F: footprint --------------------------------------------------------------------------------------


def footprint_features(readings: Mapping[int, object], event_time: int, direction: str,
                       today: Mapping[str, str]) -> tuple[float, ...] | None:
    """Per S19 family with today's threshold: (flags in break direction - flags against) / 8 over the eight 15m
    candles from one hour before the break to the break close. None when one is missing or untraded."""
    first = event_time - (FP_CANDLES - 4) * FP_CANDLE_MS
    net = dict.fromkeys(FP_FAMILIES, 0)
    for k in range(FP_CANDLES):
        reading = readings.get(first + k * FP_CANDLE_MS)
        if reading is None or not reading.traded:
            return None
        for flag in reading.flags:
            key, flag_dir = flag.split("|")
            family = key.split(":", 1)[0]
            if family in net and key == today[family]:
                net[family] += 1 if flag_dir == direction else -1
    return tuple(net[f] / FP_CANDLES for f in FP_FAMILIES)


# -- G: funding ----------------------------------------------------------------------------------------


def funding_features(rates: Sequence[tuple[int, float]], event: Event) -> tuple[float, ...] | None:
    """Last rate published by the break close (bp) and its z-score over the 90 before, in break direction.
    Positive = the side of the break already pays. None without 90 earlier rates."""
    close_time = event.time + HOUR
    known = [r for t, r in rates if t <= close_time]
    if len(known) < FUNDING_LOOKBACK + 1:
        return None
    last = known[-1]
    hist = known[-FUNDING_LOOKBACK - 1:-1]
    mean = sum(hist) / len(hist)
    sd = math.sqrt(sum((r - mean) ** 2 for r in hist) / len(hist))
    s = 1.0 if event.direction == UP else -1.0
    return (s * last * 10_000, s * (last - mean) / sd if sd > 1e-9 else 0.0)


# -- rows ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Row:
    time: int
    week: int
    section: str
    y: int
    mechanics: float  # S20 "abstand_atr"
    extra: dict[str, tuple[float, ...] | None]


def build_rows(bars: Sequence[Kline], events: Sequence[Event], footprint: Mapping[int, tuple[float, ...]] | None,
               funding: Mapping[int, tuple[float, ...]] | None) -> list[Row]:
    rows = []
    for e in events:
        extra = {"K": candle_flow(bars, e),
                 "F": footprint.get(e.time) if footprint is not None and e.time >= FP_START_MS else None,
                 "G": funding.get(e.time) if funding is not None and e.time >= FP_START_MS else None}
        rows.append(Row(e.time, s20.week_of(e.time), e.section, s20.label(bars, e),
                        s20.candle_features(bars, e)[s20.MECHANICS_FEATURE], extra))
    return rows


def family_rows(rows: Sequence[Row], family: str) -> tuple[list[Row], list[Row]]:
    inside = [r for r in rows if r.time >= START_MS[family] and r.extra.get(family) is not None]
    return [r for r in inside if r.section == "training"], [r for r in inside if r.section == "validierung"]


# -- one family against mechanics ----------------------------------------------------------------------


def _predict(train: Sequence[Row], valid: Sequence[Row], family: str | None, yt: Sequence[int]) -> list[float]:
    def x(r: Row) -> list[float]:
        return [r.mechanics] + (list(r.extra[family]) if family else [])
    model = s20.fit([x(r) for r in train], yt)
    return [model.predict(x(r)) for r in valid]


def _gain(train: Sequence[Row], valid: Sequence[Row], family: str, yt: Sequence[int], yv: Sequence[int]) -> tuple[float, list[float], list[float]]:
    base = _predict(train, valid, None, yt)
    full = _predict(train, valid, family, yt)
    return s20.rel_gain(yv, full, base), base, full


def check_family(rows: Sequence[Row], family: str, *, boot_draws: int = BOOT_DRAWS, shift_draws: int = SHIFT_DRAWS) -> dict:
    train, valid = family_rows(rows, family)
    need = MIN_EVENTS[family]
    gate = len(train) >= need["training"] and len(valid) >= need["validierung"]
    out: dict = {"familie": FAMILY_NAMES[family], "merkmale": list(FEATURES[family]),
                 "ereignisse": {"training": len(train), "validierung": len(valid)}, "gate": gate, "p": None}
    if not gate:
        return out
    yt, yv = [r.y for r in train], [r.y for r in valid]
    observed, base, full = _gain(train, valid, family, yt, yv)
    diffs = [s20.log_loss(y, b) - s20.log_loss(y, f) for y, b, f in zip(yv, base, full)]
    rng = random.Random(f"{SEED}:{family}:verschiebung")
    above = 0
    for _ in range(shift_draws):
        ot = rng.randint(MIN_SHIFT, len(yt) - MIN_SHIFT)
        ov = rng.randint(MIN_SHIFT // 2, len(yv) - MIN_SHIFT // 2)
        st, sv = yt[-ot:] + yt[:-ot], yv[-ov:] + yv[:-ov]
        above += _gain(train, valid, family, st, sv)[0] >= observed
    out.update({"rel_gewinn": observed,
                "p": s20.block_bootstrap_p([r.week for r in valid], diffs, seed=f"S21-{family}", draws=boot_draws),
                "glueckstest_p": (above + 1) / (shift_draws + 1),
                "auc_mechanik": s20.auc(yv, base), "auc_mit_familie": s20.auc(yv, full)})
    return out


# -- count and evaluate --------------------------------------------------------------------------------


def count(events: Sequence[Event], drops: Mapping[str, int], coverage: Mapping[str, set[int]]) -> dict:
    """Results-blind: events per section and how many carry each family, no label."""
    out: dict = {"verworfen": dict(sorted(drops.items())), "familien": {}}
    for family in FAMILIES:
        covered = None if family == "K" else coverage.get(family, set()) or set()
        per = {section: sum(1 for e in events if e.section == section and e.time >= START_MS[family]
                            and (covered is None or e.time in covered)) for section in ("training", "validierung")}
        need = MIN_EVENTS[family]
        out["familien"][family] = {"name": FAMILY_NAMES[family], "ereignisse": per,
                                   "gate": per["training"] >= need["training"] and per["validierung"] >= need["validierung"]}
    return out


def evaluate(rows: Sequence[Row], *, boot_draws: int = BOOT_DRAWS, shift_draws: int = SHIFT_DRAWS,
             version: str = VERSION) -> dict:
    if not version.startswith("1."):
        raise PermissionError("evaluate runs only after the rules are frozen as 1.0 (section 7)")
    results = {f: check_family(rows, f, boot_draws=boot_draws, shift_draws=shift_draws) for f in FAMILIES}
    passed_holm = holm({f: (r["p"] if r["p"] is not None else 1.0) for f, r in results.items()}, HOLM_M, ALPHA)
    verdicts = {}
    for f, r in results.items():
        ok = bool(r["gate"] and f in passed_holm and r["rel_gewinn"] >= MIN_REL_GAIN and r["glueckstest_p"] < ALPHA)
        verdicts[f] = "BESTANDEN (Kandidat)" if ok else ("nicht testbar (Gate)" if not r["gate"] else "NICHT BESTANDEN")
    return {"familien": results, "holm_bestanden": sorted(passed_holm), "urteile": verdicts,
            "urteil": ("BESTANDEN: " + ", ".join(FAMILY_NAMES[f] for f, v in verdicts.items() if v.startswith("BEST")))
            if any(v.startswith("BEST") for v in verdicts.values())
            else "NICHT BESTANDEN: keine Familie sagt den Flip besser voraus als der Abstand zur Linie allein"}


# -- data and CLI --------------------------------------------------------------------------------------


def load_footprint(root: Path, events: Sequence[Event], *, workers: int = 1, cache: Path | None = None) -> dict[int, tuple[float, ...]]:
    from src.research_lab.studies import s19
    readings, _ = s19.read_range(root, date(2020, 1, 1), date(2024, 12, 31), workers=workers, cache=cache)
    by_start = {r.start: r for r in readings}
    out = {}
    for e in events:
        if e.time >= FP_START_MS:
            feats = footprint_features(by_start, e.time, e.direction, s19.TODAY_KEYS)
            if feats is not None:
                out[e.time] = feats
    return out


def load_funding(root: Path, events: Sequence[Event], *, fetch: bool = False) -> dict[int, tuple[float, ...]]:
    from src.research_lab.data.archive import ArchiveRef, Dataset, Market
    from src.research_lab.data.store import ArchiveStore, months
    store = ArchiveStore(root)
    refs = [ArchiveRef(Market.USDM, Dataset.FUNDING, y, m, symbol=s20.SYMBOL) for y, m in months(FUNDING_FIRST_MONTH, s20.LAST_MONTH)]
    if fetch:
        for ref in refs:
            store.fetch(ref)
    rates = [(f.time, f.rate) for f in store.load_funding(refs)]
    times = [t for t, _ in rates]
    out = {}
    for e in events:
        if e.time >= FP_START_MS:
            cut = bisect_right(times, e.time + HOUR)
            feats = funding_features(rates[max(0, cut - FUNDING_LOOKBACK - 1):cut], e)
            if feats is not None:
                out[e.time] = feats
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s21")
    parser.add_argument("step", choices=("count", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fehlende Kerzen- und Funding-Monatsdateien laden (nur bis 2024-12)")
    parser.add_argument("--footprint", type=Path, help="S8-Store (wie S19 --bars); ohne: Familie F nicht testbar")
    parser.add_argument("--fp-cache", type=Path, help="Tages-Cache der S19-Lesungen (mit S19 geteilt)")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    bars, digest = s20.load(args.root, fetch=args.fetch)
    events, drops = s20.find_events(bars)
    fp = load_footprint(args.footprint, events, workers=args.workers, cache=args.fp_cache) if args.footprint else None
    funding = load_funding(args.root, events, fetch=args.fetch)
    coverage = {"F": set(fp) if fp is not None else None, "G": set(funding)}
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    result = {"studie": "S21", "version": VERSION, "seed": SEED, "datensatz_sha256": digest, "kerzen": len(bars),
              "zaehllauf": count(events, drops, coverage)}
    if args.step == "evaluate":
        result["auswertung"] = evaluate(build_rows(bars, events, fp, funding))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"s21_{args.step}_{stamp}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)
    print(json.dumps(result["zaehllauf"], ensure_ascii=False))
    if "auswertung" in result:
        print(result["auswertung"]["urteil"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
