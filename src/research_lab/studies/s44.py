"""S44: follow the breakout of a defended range (stage A: Binance 1m candles, days outside the 55 Tardis days).

Rules: docs/research_lab/studien/S44_AUSBRUCH_FOLGEN_PRAEREGISTRIERUNG_ENTWURF.md (draft 0.1).

The idea comes from S32-R (narrow defended ranges almost always break out within 60 minutes, direction a coin flip),
so it is never tested on the 55 Tardis days S32-R saw. Stage A uses Binance USD-M BTCUSDT 1-minute candles on all
other days from 2020-06-01 to 2024-12-31 (training to 2022-12-31, validation 2023-2024, holdout from 2025 refused).
Stage B (with the order book, recorder data #253) gets its own frozen rules before any recorder day is looked at.

Per UTC day, on 1-minute closes (the candle close stands in for the mid of S32):

1. range: 15-minute window, both edges defended as in S32 1.0 (``s32.defended`` on the closes), at least 14 of 15
   closes present, widths 10-20 / 20-60 / 60-100 / 100-150 bp, each also per session (20 groups); a range is counted
   once in the minute it first counts as defended, then not again for 60 minutes in that group (as S32-R);
2. breakout: within 60 minutes, the first candle whose high reaches ``hi + 0.25 x width`` or whose low reaches
   ``lo - 0.25 x width`` (S32-R). A candle that reaches both is "unklar" and gives no trade (counted);
3. entry: market (taker) at the open of the next candle, in the breakout direction; stop at the range middle;
   target ``k x width`` from the entry, k = 1, 2, 3, each its own question; time exit at the close 60 candles after
   the entry. Within a candle the stop is checked first (conservative). An entry already on the wrong side of the
   stop is "no_room";
4. costs: protocol 1.3 taker (13 bp, with stop 18 bp), stress doubled (as S32).

Test per group and target: mean net R; lower bound by block bootstrap over days (alpha 0.05 per group, one-sided);
passed if above 0 in training and validation. Below 30 trades in a section: shown, no verdict.

    python -m src.research_lab.studies.s44 count    --root data/research_lab --out DIR [--fetch]
    python -m src.research_lab.studies.s44 evaluate --root data/research_lab --out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.research_lab.data.parse import Kline
from src.research_lab.protocol import BASE_COSTS, STRESS_COSTS
from src.research_lab.studies import s32
from src.research_lab.studies.s32 import Outcome

VERSION = "0.1"
SEED = 44
MIN_CASES = 30
ALPHA = 0.05
BOOT_DRAWS = 9_999
FIRST_DAY, LAST_DAY = date(2020, 6, 1), date(2024, 12, 31)
TARGETS_K = (1, 2, 3)
GROUPS = s32.GROUPS
MINUTE_MS = 60_000


@dataclass(frozen=True)
class Config:
    window_m: int = 15  # as S32 1.0 (900 s)
    min_present: int = 14  # of 15 closes (S32: 95 % valid seconds)
    horizon_m: int = 60  # breakout search and holding time (S32-R: 60 min, Uzi #315)
    breakout: float = 0.25  # share of the width beyond the edge (S32-R)

    def digest(self) -> str:
        base = {"s44": asdict(self), "s32": asdict(s32.CONFIG), "targets_k": TARGETS_K, "groups": GROUPS,
                "first_day": FIRST_DAY.isoformat(), "last_day": LAST_DAY.isoformat()}
        return hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()


CONFIG = Config()


@dataclass(frozen=True)
class Bar:
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class Range:
    day: str
    i: int  # minute of the day in which the range first counts as defended
    lo: float
    hi: float
    width_bp: float


@dataclass(frozen=True)
class Breakout:
    rng: Range
    j: int  # breakout minute, -1 if none within the horizon
    side: int  # +1 up, -1 down, 0 none or unclear
    kind: str  # oben / unten / bleibt / unklar / missing


def study_days() -> list[date]:
    """All days of stage A: 2020-06-01 to 2024-12-31 without the 55 Tardis days S32 / S32-R used."""
    seen = set(s32.study_days())
    out, d = [], FIRST_DAY
    while d <= LAST_DAY:
        if d not in seen:
            out.append(d)
        d += timedelta(days=1)
    return out


def section(day: date) -> str:
    return s32.section(day)


def day_bars(klines: Sequence[Kline], day: date) -> list[Bar | None]:
    """The 1440 minutes of one UTC day; a missing candle is None."""
    start = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp() * 1000)
    out: list[Bar | None] = [None] * 1440
    for k in klines:
        m = (k.open_time - start) // MINUTE_MS
        if 0 <= m < 1440:
            out[m] = Bar(k.open, k.high, k.low, k.close)
    return out


def group_of(r: Range) -> str | None:
    return s32.width_group(r.width_bp)


def in_group(r: Range, grp: str) -> bool:
    width, _, ses = grp.partition("|")
    return group_of(r) == width and (not ses or s32.session_of(r.i * 60) == ses)


def find_ranges(bars: Sequence[Bar | None], day: str, cfg: Config = CONFIG) -> list[Range]:
    out: list[Range] = []
    last: dict[str, int] = {}
    lo_q: deque[tuple[int, float]] = deque()
    hi_q: deque[tuple[int, float]] = deque()
    present = 0
    w = cfg.window_m
    for i, b in enumerate(bars):
        if i - w >= 0 and bars[i - w] is not None:
            present -= 1
        while lo_q and lo_q[0][0] <= i - w:
            lo_q.popleft()
        while hi_q and hi_q[0][0] <= i - w:
            hi_q.popleft()
        if b is None:
            continue
        present += 1
        while lo_q and lo_q[-1][1] >= b.close:
            lo_q.pop()
        lo_q.append((i, b.close))
        while hi_q and hi_q[-1][1] <= b.close:
            hi_q.pop()
        hi_q.append((i, b.close))
        if i < w - 1 or present < cfg.min_present:
            continue
        lo, hi = lo_q[0][1], hi_q[0][1]
        if hi <= lo:
            continue
        width_bp = (hi - lo) / b.close * 10_000
        grp = s32.width_group(width_bp)
        if grp is None or i - last.get(grp, -10**9) < cfg.horizon_m:
            continue
        window = [x.close for x in bars[i - w + 1: i + 1] if x is not None]
        if not s32.defended(window, lo, hi):
            continue
        last[grp] = i
        out.append(Range(day=day, i=i, lo=lo, hi=hi, width_bp=width_bp))
    return out


def find_breakout(bars: Sequence[Bar | None], r: Range, cfg: Config = CONFIG) -> Breakout:
    w = r.hi - r.lo
    up, down = r.hi + cfg.breakout * w, r.lo - cfg.breakout * w
    if r.i + cfg.horizon_m >= len(bars):
        return Breakout(r, -1, 0, "missing")
    for j in range(r.i + 1, r.i + cfg.horizon_m + 1):
        b = bars[j]
        if b is None:
            continue
        hit_up, hit_down = b.high >= up, b.low <= down
        if hit_up and hit_down:
            return Breakout(r, j, 0, "unklar")
        if hit_up or hit_down:
            return Breakout(r, j, 1 if hit_up else -1, "oben" if hit_up else "unten")
    return Breakout(r, -1, 0, "bleibt")


def follow(bars: Sequence[Bar | None], bo: Breakout, k: int, cfg: Config = CONFIG) -> Outcome:
    """Market entry at the next open in the breakout direction, stop at the range middle, target k x width."""
    if bo.side == 0:
        return Outcome(bo.kind, 0.0, 0.0)
    e = bo.j + 1
    if e + cfg.horizon_m >= len(bars) or bars[e] is None:
        return Outcome("missing", 0.0, 0.0)
    r, side = bo.rng, bo.side
    entry = bars[e].open
    stop = (r.lo + r.hi) / 2
    target = entry + side * k * (r.hi - r.lo)
    if (entry - stop) * side <= 0:
        return Outcome("no_room", 0.0, 0.0)
    risk_bp = abs(entry - stop) / entry * 10_000
    last_close = entry
    for m in range(e, e + cfg.horizon_m):
        b = bars[m]
        if b is None:
            continue
        if (b.low if side > 0 else b.high) * side <= stop * side:
            return Outcome("stop", (stop - entry) / entry * 10_000 * side, risk_bp)
        if (b.high if side > 0 else b.low) * side >= target * side:
            return Outcome("target", (target - entry) / entry * 10_000 * side, risk_bp)
        last_close = b.close
    return Outcome("time", (last_close - entry) / entry * 10_000 * side, risk_bp)


def net_r(o: Outcome) -> float:
    return s32.net_r(o, BASE_COSTS)


def net_r_stress(o: Outcome) -> float:
    return s32.net_r(o, STRESS_COSTS)


def count(breakouts: dict[date, list[Breakout]]) -> dict:
    """Results-blind: ranges and breakouts (the case count) per section and group, no exits, no net R."""
    out: dict = {}
    for name in ("training", "validierung"):
        out[name] = {"tage": sum(section(d) == name for d in breakouts)}
        for grp in GROUPS:
            rows = [b for d, bs in breakouts.items() if section(d) == name for b in bs if in_group(b.rng, grp)]
            n = sum(b.side != 0 for b in rows)
            out[name][grp] = {"ranges": len(rows), "ausbrueche": n, "unklar": sum(b.kind == "unklar" for b in rows),
                              "pruefbar": n >= MIN_CASES}
    return out


def _boot_lower(days: list[list[float]], draws: int, rng: random.Random, alpha: float = ALPHA) -> float:
    vals = []
    for _ in range(draws):
        xs = [x for _ in days for x in days[rng.randrange(len(days))]]
        if xs:
            vals.append(sum(xs) / len(xs))
    vals.sort()
    return vals[int(alpha * len(vals))] if vals else float("nan")


def evaluate(results: dict[int, dict[date, list[tuple[Breakout, Outcome]]]], *, version: str = VERSION,
             draws: int = BOOT_DRAWS, seed: int = SEED) -> dict:
    if not version.startswith("1."):
        raise PermissionError("evaluate runs only after the rules are frozen as 1.0")
    rng = random.Random(seed)
    out: dict = {}
    for k in TARGETS_K:
        fam: dict = {}
        for name in ("training", "validierung"):
            fam[name] = {}
            for grp in GROUPS:
                days = [[net_r(o) for b, o in rows if in_group(b.rng, grp) and o.exit in ("target", "stop", "time")]
                        for d, rows in sorted(results[k].items()) if section(d) == name]
                days = [d for d in days if d]
                flat = [o for d, rows in results[k].items() if section(d) == name for b, o in rows
                        if in_group(b.rng, grp) and o.exit in ("target", "stop", "time")]
                n = len(flat)
                fam[name][grp] = {
                    "trades": n, "pruefbar": n >= MIN_CASES,
                    "netto_r": sum(net_r(o) for o in flat) / n if n else None,
                    "netto_r_stress": sum(net_r_stress(o) for o in flat) / n if n else None,
                    "anteile": {x: sum(o.exit == x for o in flat) / n for x in ("target", "stop", "time")} if n else None,
                    "untere_grenze": _boot_lower(days, draws, rng) if n >= MIN_CASES else None}
        fam["ergebnis"] = {grp: bool(fam["training"][grp]["pruefbar"] and fam["validierung"][grp]["pruefbar"]
                                     and fam["training"][grp]["untere_grenze"] > 0
                                     and fam["validierung"][grp]["untere_grenze"] > 0) for grp in GROUPS}
        out[f"ziel_{k}x"] = fam
    return out


def refs():
    from src.research_lab.data.archive import ArchiveRef, Dataset, Market
    from src.research_lab.data.store import months
    return [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, interval="1m")
            for y, m in months((FIRST_DAY.year, FIRST_DAY.month), (LAST_DAY.year, LAST_DAY.month))]


def main(argv: Sequence[str] | None = None) -> int:
    from src.research_lab.data.store import ArchiveStore
    from src.research_lab.protocol import HOLDOUT_START_MS
    p = argparse.ArgumentParser(prog="python -m src.research_lab.studies.s44")
    p.add_argument("step", choices=("count", "evaluate"))
    p.add_argument("--root", type=Path, default=Path("data/research_lab"))
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--fetch", action="store_true", help="fehlende Monatsdateien von data.binance.vision laden (bis 2024-12)")
    a = p.parse_args(argv)
    if a.step == "evaluate" and not VERSION.startswith("1."):
        raise SystemExit("evaluate is locked while S44 is a draft")
    store, rs = ArchiveStore(a.root), refs()
    if a.fetch:
        for ref in rs:
            store.fetch(ref)
    by_day: dict[date, list[Kline]] = {}
    for kl in store.load_klines(rs):
        if kl.open_time < HOLDOUT_START_MS:
            by_day.setdefault(datetime.fromtimestamp(kl.open_time / 1000, timezone.utc).date(), []).append(kl)
    breakouts: dict[date, list[Breakout]] = {}
    results: dict[int, dict] = {k: {} for k in TARGETS_K}
    for day in study_days():
        bars = day_bars(by_day.get(day, []), day)
        breakouts[day] = [find_breakout(bars, r) for r in find_ranges(bars, day.isoformat())]
        if a.step == "evaluate":
            for k in TARGETS_K:
                results[k][day] = [(b, follow(bars, b, k)) for b in breakouts[day]]
    report = {"studie": "S44", "stufe": "A", "version": VERSION, "config_sha256": CONFIG.digest(),
              "datensatz_sha256": store.dataset_hash(rs), "tage": len(study_days())}
    report["zaehlung" if a.step == "count" else "auswertung"] = count(breakouts) if a.step == "count" else evaluate(results)
    a.out.mkdir(parents=True, exist_ok=True)
    path = a.out / f"s44_{a.step}_{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
