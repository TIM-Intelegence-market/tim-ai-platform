"""S32-R: where does a defended range go? Companion study to S32, same data, frozen together with S32.

Rules: docs/research_lab/studien/S32R_RANGE_RICHTUNG_PRAEREGISTRIERUNG_ENTWURF.md (draft 0.1).
Data and range detection as in :mod:`src.research_lab.studies.s32` (Tardis free days 2020-06 to 2024-12, holdout from
2025-01-01 refused, 15-minute window, both edges defended, width groups 10-20 / 20-60 / 60-100 / 100-150 bp, each
width also per session; every group is its own question).

1. range: counted once, in the second it first counts as defended; then not again for ``horizon_s`` in that group;
2. book: ratio bid / ask within ±5 bp of the mid. Over 1 means the upper side is thinner. Of the last 3 seconds
   the value closest to 1 is taken (the imbalance must hold);
3. outcome within 60 minutes (Uzi, issue #315): first the mid lies a quarter of the width beyond the upper edge
   ("oben"), beyond the lower edge ("unten"), or neither ("bleibt"). Whether a breakout still holds 60 minutes later
   is reported, not tested.

B (base rates per group) is descriptive. A1: among breakouts, does the share of "oben" rise with the log ratio
(slope)? A2: do ranges break out more often the more lopsided the book is (slope of "breakout" on |log ratio|)?
Per group alpha 0.05, half for A1, half for A2; lower bound by block bootstrap over days; pass if > 0 in training
and validation. Below 30 cases in a section: shown, no verdict.

    python -m src.research_lab.studies.s32r count    --dir ~/TIM-research/tardis --out DIR [--fetch]
    python -m src.research_lab.studies.s32r evaluate --dir ~/TIM-research/tardis --out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
from collections import deque
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from src.research_lab.studies import s32
from src.research_lab.studies.s32 import Second

VERSION = "0.1"
SEED = 3232
MIN_CASES = 30
ALPHA = 0.05
ALPHA_A = ALPHA / 2  # per group: half for A1, half for A2
BOOT_DRAWS = 9_999
RATIO_CLIP = 10.0  # log ratio clipped to 1:10 ... 10:1


@dataclass(frozen=True)
class Config:
    horizon_s: int = 3600  # Uzi 17.11.2026 (#315)
    breakout: float = 0.25  # share of the width beyond the edge (Uzi 17.11.2026, #315)
    hold_s: int = 3

    def digest(self) -> str:
        base = asdict(s32.CONFIG)
        base.update({f"r_{k}": v for k, v in asdict(self).items()})
        return hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()


CONFIG = Config()


@dataclass(frozen=True)
class Range:
    day: str
    i: int
    lo: float
    hi: float
    width_bp: float
    ratio: float  # bid / ask, > 1: upper side thinner


def book_ratio(recent: Sequence[Second]) -> float | None:
    """bid/ask of the last seconds, the value closest to 1; None if a side is empty."""
    vals = []
    for s in recent:
        if s.bid_q <= 0 or s.ask_q <= 0:
            return None
        vals.append(s.bid_q / s.ask_q)
    return min(vals, key=lambda r: abs(math.log(r)))


def find_ranges(secs: Sequence[Second | None], day: str, cfg: Config = CONFIG,
                base: s32.Config = s32.CONFIG) -> list[Range]:
    out: list[Range] = []
    last: dict[str, int] = {}
    lo_q: deque[tuple[int, float]] = deque()
    hi_q: deque[tuple[int, float]] = deque()
    valid = 0
    w = base.window_s
    for i, s in enumerate(secs):
        if i - w >= 0 and secs[i - w] is not None:
            valid -= 1
        while lo_q and lo_q[0][0] <= i - w:
            lo_q.popleft()
        while hi_q and hi_q[0][0] <= i - w:
            hi_q.popleft()
        if s is None:
            continue
        valid += 1
        while lo_q and lo_q[-1][1] >= s.mid:
            lo_q.pop()
        lo_q.append((i, s.mid))
        while hi_q and hi_q[-1][1] <= s.mid:
            hi_q.pop()
        hi_q.append((i, s.mid))
        if i < w or valid < base.min_valid_share * w:
            continue
        lo, hi = lo_q[0][1], hi_q[0][1]
        width_bp = (hi - lo) / s.mid * 10_000
        group = s32.width_group(width_bp, base)
        if group is None or i - last.get(group, -10**9) < cfg.horizon_s:
            continue
        recent = secs[i - cfg.hold_s + 1: i + 1]
        if any(x is None for x in recent):
            continue
        ratio = book_ratio(recent)
        if ratio is None:
            continue
        window = [x.mid for x in secs[i - w + 1: i + 1] if x is not None]
        if not s32.defended(window, lo, hi, base):
            continue
        last[group] = i
        out.append(Range(day=day, i=i, lo=lo, hi=hi, width_bp=width_bp, ratio=ratio))
    return out


def group_of(r: Range) -> str:
    return s32.width_group(r.width_bp)


def in_group(r: Range, grp: str) -> bool:
    width, _, ses = grp.partition("|")
    return group_of(r) == width and (not ses or s32.session_of(r.i) == ses)


@dataclass(frozen=True)
class Result:
    exit: str  # oben / unten / bleibt / missing
    holds: bool | None  # breakout still beyond the edge 60 minutes after it happened (None if not known)


def outcome(secs: Sequence[Second | None], r: Range, cfg: Config = CONFIG) -> Result:
    w = r.hi - r.lo
    up, down = r.hi + cfg.breakout * w, r.lo - cfg.breakout * w
    end = r.i + cfg.horizon_s
    if end >= len(secs):
        return Result("missing", None)
    for j in range(r.i + 1, end + 1):
        s = secs[j]
        if s is None:
            continue
        if s.mid >= up or s.mid <= down:
            kind = "oben" if s.mid >= up else "unten"
            k = j + cfg.horizon_s
            later = next((secs[m] for m in range(k, min(k + 60, len(secs))) if secs[m] is not None), None)
            holds = None if later is None else (later.mid > r.hi if kind == "oben" else later.mid < r.lo)
            return Result(kind, holds)
    return Result("bleibt", None)


def _x(ratio: float) -> float:
    return math.log(min(max(ratio, 1 / RATIO_CLIP), RATIO_CLIP))


def _slope(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    mx = sum(x for x, _ in pairs) / len(pairs)
    my = sum(y for _, y in pairs) / len(pairs)
    sxx = sum((x - mx) ** 2 for x, _ in pairs)
    if sxx <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in pairs) / sxx


def a1(rows: Sequence[tuple[Range, Result]]) -> float | None:
    """Among breakouts: slope of "oben" on the log ratio (positive = breakouts go to the thin side)."""
    return _slope([(_x(r.ratio), 1.0 if o.exit == "oben" else 0.0) for r, o in rows if o.exit in ("oben", "unten")])


def a2(rows: Sequence[tuple[Range, Result]]) -> float | None:
    """Slope of "breakout at all" on |log ratio| (positive = lopsided books break out more often)."""
    return _slope([(abs(_x(r.ratio)), 0.0 if o.exit == "bleibt" else 1.0) for r, o in rows
                   if o.exit in ("oben", "unten", "bleibt")])


def _boot_lower(days, stat, draws: int, rng: random.Random) -> float | None:
    vals = []
    for _ in range(draws):
        v = stat([x for _ in days for x in days[rng.randrange(len(days))]])
        if v is not None:
            vals.append(v)
    vals.sort()
    return vals[int(ALPHA_A * len(vals))] if vals else None


def count(ranges_by_day: dict[date, list[Range]]) -> dict:
    """Results-blind: ranges per section and group, and how many have an upper / lower thinner book."""
    out: dict = {"training": {}, "validierung": {}, "je_tag": {}}
    for day, rs in sorted(ranges_by_day.items()):
        out["je_tag"][day.isoformat()] = len(rs)
    for name in ("training", "validierung"):
        rs = [r for d, xs in ranges_by_day.items() if s32.section(d) == name for r in xs]
        for grp in s32.GROUPS:
            g = [r for r in rs if in_group(r, grp)]
            out[name][grp] = {"ranges": len(g), "oben_duenner": sum(r.ratio > 1 for r in g),
                              "mit_urteil": len(g) >= MIN_CASES}
    return out


def evaluate(results: dict[date, list[tuple[Range, Result]]], *, version: str = VERSION,
             draws: int = BOOT_DRAWS) -> dict:
    if not version.startswith("1."):
        raise PermissionError("evaluate runs only after the rules are frozen as 1.0")
    rng = random.Random(SEED)
    out: dict = {}
    for name in ("training", "validierung"):
        out[name] = {}
        for grp in s32.GROUPS:
            days = [[(r, o) for r, o in rows if in_group(r, grp) and o.exit != "missing"]
                    for d, rows in sorted(results.items()) if s32.section(d) == name]
            days = [d for d in days if d]
            flat = [x for d in days for x in d]
            n_break = sum(o.exit in ("oben", "unten") for _, o in flat)
            held = [o.holds for _, o in flat if o.holds is not None]
            base = {k: sum(o.exit == k for _, o in flat) for k in ("oben", "unten", "bleibt")}
            out[name][grp] = {
                "ranges": len(flat), "ausbrueche": n_break, "grundverhalten": base,
                "ausbruch_haelt_60min": (sum(held) / len(held)) if held else None,
                "a1_steigung": a1(flat), "a2_steigung": a2(flat),
                "a1_untere_grenze": _boot_lower(days, a1, draws, rng) if n_break >= MIN_CASES else None,
                "a2_untere_grenze": _boot_lower(days, a2, draws, rng) if len(flat) >= MIN_CASES else None,
            }
    out["ergebnis"] = {}
    for grp in s32.GROUPS:
        t, v = out["training"][grp], out["validierung"][grp]

        def ok(key, t=t, v=v):
            return t[key] is not None and v[key] is not None and t[key] > 0 and v[key] > 0

        out["ergebnis"][grp] = {"a1_bestanden": ok("a1_untere_grenze"), "a2_bestanden": ok("a2_untere_grenze"),
                                "mit_urteil": t["a2_untere_grenze"] is not None and v["a2_untere_grenze"] is not None}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.research_lab.studies.s32r")
    p.add_argument("step", choices=("count", "evaluate"))
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--fetch", action="store_true")
    a = p.parse_args(argv)
    folder, out_dir = a.dir.expanduser(), a.out.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.step == "evaluate" and not VERSION.startswith("1."):
        raise SystemExit("evaluate is locked while S32-R is a draft")
    ranges: dict[date, list[Range]] = {}
    results: dict[date, list[tuple[Range, Result]]] = {}
    for day in s32.study_days():
        secs = s32.load_day(folder, day, fetch=a.fetch)
        ranges[day] = find_ranges(secs, day.isoformat())
        if a.step == "evaluate":
            results[day] = [(r, outcome(secs, r)) for r in ranges[day]]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    report = {"studie": "S32-R", "version": VERSION, "config_sha256": CONFIG.digest(), "tage": len(ranges),
              "zaehlung" if a.step == "count" else "auswertung": count(ranges) if a.step == "count"
              else evaluate(results)}
    path = out_dir / f"s32r_{a.step}_{stamp}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
