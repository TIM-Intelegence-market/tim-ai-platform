"""S42: the S32 setup on larger ranges (1 h, 2 h, 4 h windows). Follow-up to S32, own question, own data run.

Rules: docs/research_lab/studien/S42_S43_ORDERBUCH_GROSSE_RANGES_MAKER_PRAEREGISTRIERUNG_ENTWURF.md (1.0, frozen 25.11.2026).

S32 found no edge on 15-minute ranges; costs (13-18 bp) were larger than the whole stop on narrow ranges. The setup
in the video comes from a market where costs are tiny against the stop, so S42 asks the same chain on ranges that are
wide enough for costs to matter less. Everything is as in S32 (book ±5 bp, imbalance held 3 s, defended range,
lower/upper quarter, stop 5 bp beyond the edge, entry 1 s later, both targets, H1 trend over all ratios, H2 net R per
ratio bin, every group its own question, below 30 cases no verdict) except:

- range window 1 h, 2 h and 4 h, each window its own family of questions;
- widths 60-100, 100-150, 150-250, 250-400 bp, each also per session;
- horizon and cooldown = a third of the window (S32: 300 s for 900 s);
- the defended check runs at most every ``check_s`` seconds per window (4-hour windows are too slow otherwise).

``count`` is results-blind. ``evaluate`` refuses to run while ``VERSION`` is a draft.

    python -m src.research_lab.studies.s42 count    --dir ~/TIM-research/tardis --out DIR [--fetch]
    python -m src.research_lab.studies.s42 evaluate --dir ~/TIM-research/tardis --out DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone
from pathlib import Path

from src.research_lab.protocol import BASE_COSTS, STRESS_COSTS
from src.research_lab.stats.deflated import deflated_sharpe
from src.research_lab.studies import s32
from src.research_lab.studies.s32 import Event, Outcome, Second

VERSION = "1.0"
SEED = 42
MIN_CASES = s32.MIN_CASES
BOOT_DRAWS = s32.BOOT_DRAWS
ALPHA = 0.05
ALPHA_H1 = ALPHA / 2
ALPHA_H2 = ALPHA / 2 / s32.H2_BINS
WINDOWS = {"1h": 3600, "2h": 7200, "4h": 14400}
WIDTH_GROUPS = ((60.0, 100.0), (100.0, 150.0), (150.0, 250.0), (250.0, 400.0))
WIDTH_LABELS = tuple(f"{lo:g}-{hi:g}" for lo, hi in WIDTH_GROUPS)
GROUPS = WIDTH_LABELS + tuple(f"{w}|{name}" for w in WIDTH_LABELS for name, _ in s32.SESSIONS)
# Multiple testing (pre-registration section 5): every H2 field of S32 1.0, S42 and S43, the trial count for the
# deflated Sharpe that is reported (descriptive, not a pass condition) for every passed H2 field.
H2_FIELDS_TOTAL = (len(s32.GROUPS) * 2 * s32.H2_BINS  # S32: groups x 2 targets x bins
                   + len(WINDOWS) * len(GROUPS) * 2 * s32.H2_BINS  # S42
                   + (len(WINDOWS) + 1) * 3 * len(GROUPS) * 2 * s32.H2_BINS)  # S43: 4 windows x 3 cancel times


@dataclass(frozen=True)
class Config:
    check_s: int = 10  # defended check at most every 10 s per window (same rule for every window)

    def chain(self, window_s: int) -> s32.Config:
        """The S32 chain with this window; horizon and cooldown a third of the window."""
        return replace(s32.CONFIG, window_s=window_s, horizon_s=window_s // 3, cooldown_s=window_s // 3)

    def digest(self) -> str:
        base = {"s42": asdict(self), "windows": WINDOWS, "widths": WIDTH_GROUPS,
                "chains": {k: asdict(self.chain(v)) for k, v in WINDOWS.items()}}
        return hashlib.sha256(json.dumps(base, sort_keys=True).encode()).hexdigest()


CONFIG = Config()


def width_group(width_bp: float) -> str | None:
    for lo, hi in WIDTH_GROUPS:
        if lo <= width_bp < hi:
            return f"{lo:g}-{hi:g}"
    return None


def in_group(e: Event, grp: str) -> bool:
    width, _, ses = grp.partition("|")
    return width_group(e.width_bp) == width and (not ses or s32.session_of(e.i) == ses)


def find_events(secs: Sequence[Second | None], day: str, chain: s32.Config, check_s: int = CONFIG.check_s,
                group_of: Callable[[float], str | None] = width_group) -> list[Event]:
    """Like :func:`s32.find_events` with its own width groups; the defended check runs at most every ``check_s``."""
    events: list[Event] = []
    last: dict[str, int] = {}
    last_check: dict[str, int] = {}
    lo_q: deque[tuple[int, float]] = deque()
    hi_q: deque[tuple[int, float]] = deque()
    valid = 0
    w = chain.window_s
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
        if i < w or valid < chain.min_valid_share * w:
            continue
        lo, hi = lo_q[0][1], hi_q[0][1]
        group = group_of((hi - lo) / s.mid * 10_000)
        if group is None or i - last.get(group, -10**9) < chain.cooldown_s:
            continue
        pos = (s.mid - lo) / (hi - lo)
        want = 1 if pos <= chain.position else (-1 if pos >= 1 - chain.position else 0)
        if want == 0:
            continue
        recent = secs[i - chain.hold_s + 1: i + 1]
        if any(x is None for x in recent):
            continue
        ratios = [s32.side_ratio(x, want) for x in recent]
        if any(r is None for r in ratios):
            continue
        if i - last_check.get(group, -10**9) < check_s:
            continue
        last_check[group] = i
        window = [x.mid for x in secs[i - w + 1: i + 1] if x is not None]
        if not s32.defended(window, lo, hi, chain):
            continue
        last[group] = i
        events.append(Event(day=day, i=i, side=want, ratio=min(ratios), lo=lo, hi=hi,
                            width_bp=(hi - lo) / s.mid * 10_000))
    return events


# -- count and evaluate (shared with S43) -------------------------------------------------------------------


def count(events_by_day: dict[date, list[Event]], groups: Sequence[str] = GROUPS,
          member: Callable[[Event, str], bool] = in_group) -> dict:
    """Results-blind: cases per section and group, and which ratio bins reach 30 cases."""
    out: dict = {"training": {}, "validierung": {}}
    for name in ("training", "validierung"):
        evs = [e for d, es in events_by_day.items() if s32.section(d) == name for e in es]
        for grp in groups:
            g = [e for e in evs if member(e, grp)]
            per_bin: dict[str, int] = {}
            for e in g:
                per_bin[s32.bin_label(e.ratio)] = per_bin.get(s32.bin_label(e.ratio), 0) + 1
            out[name][grp] = {"alle": len(g), "pruefbar": len(g) >= MIN_CASES,
                              "h2_pruefbare_stufen": sorted(b for b, n in per_bin.items() if n >= MIN_CASES)}
    return out


def _boot_lower(days, stat, draws: int, rng: random.Random, alpha: float) -> float:
    vals = []
    for _ in range(draws):
        v = stat([r for _ in days for r in days[rng.randrange(len(days))]])
        if v is not None:
            vals.append(v)
    vals.sort()
    return vals[int(alpha * len(vals))] if vals else float("nan")


def _dsr(xs: Sequence[float]) -> float | None:
    try:
        return deflated_sharpe(xs, H2_FIELDS_TOTAL).dsr
    except (ValueError, ZeroDivisionError):
        return None


def evaluate(results: dict[date, list[tuple[Event, Outcome]]], *, groups: Sequence[str] = GROUPS,
             member: Callable[[Event, str], bool] = in_group, net=None, net_stress=None,
             valid_exits: tuple[str, ...] = ("target", "stop", "time"), version: str = VERSION,
             draws: int = BOOT_DRAWS, seed: int = SEED) -> dict:
    """H1 (trend of "target first" over the log ratio) and H2 (net R per ratio bin) per group, as in S32."""
    if not version.startswith("1."):
        raise PermissionError("evaluate runs only after the rules are frozen as 1.0")
    net = net or (lambda o: s32.net_r(o, BASE_COSTS))
    net_stress = net_stress or (lambda o: s32.net_r(o, STRESS_COSTS))
    rng = random.Random(seed)
    out: dict = {}
    for name in ("training", "validierung"):
        out[name] = {}
        for grp in groups:
            days = [[(e.ratio, o) for e, o in rows if member(e, grp) and o.exit in valid_exits]
                    for d, rows in sorted(results.items()) if s32.section(d) == name]
            days = [d for d in days if d]
            flat = [r for d in days for r in d]

            def mean_in(label, f=net):
                def stat(sample):
                    xs = [f(o) for r, o in sample if s32.bin_label(r) == label]
                    return sum(xs) / len(xs) if xs else None
                return stat

            h2 = {}
            for label in sorted({s32.bin_label(r) for r, _ in flat}):
                n = sum(s32.bin_label(r) == label for r, _ in flat)
                h2[label] = {"n": n, "pruefbar": n >= MIN_CASES, "netto_r": mean_in(label)(flat),
                             "netto_r_stress": mean_in(label, net_stress)(flat),
                             "ziel_zuerst": sum(o.exit == "target" for r, o in flat if s32.bin_label(r) == label) / n,
                             "untere_grenze": _boot_lower(days, mean_in(label), draws, rng, ALPHA_H2)
                             if n >= MIN_CASES else None}
            ok = len(flat) >= MIN_CASES
            out[name][grp] = {"alle": len(flat), "pruefbar": ok, "h1_steigung": s32.slope(flat),
                              "h1_untere_grenze": _boot_lower(days, s32.slope, draws, rng, ALPHA_H1) if ok else None,
                              "netto_r_alle": (sum(net(o) for _, o in flat) / len(flat)) if flat else None,
                              "h2_je_verhaeltnis": h2}
    out["ergebnis"] = {}
    for grp in groups:
        t, v = out["training"][grp], out["validierung"][grp]
        passed = [lb for lb, b in t["h2_je_verhaeltnis"].items()
                  if b["pruefbar"] and b["untere_grenze"] > 0 and v["h2_je_verhaeltnis"].get(lb, {}).get("pruefbar")
                  and v["h2_je_verhaeltnis"][lb]["untere_grenze"] > 0]
        out["ergebnis"][grp] = {
            "h1_pruefbar": bool(t["pruefbar"] and v["pruefbar"]),
            "h1_bestanden": bool(t["pruefbar"] and v["pruefbar"]
                                 and t["h1_untere_grenze"] > 0 and v["h1_untere_grenze"] > 0),
            "h2_bestandene_stufen": passed, "h2_bestanden": bool(passed),
            "h2_deflated_sharpe": {lb: _dsr([net(o) for d, rows in results.items() for e, o in rows
                                             if member(e, grp) and o.exit in valid_exits
                                             and s32.bin_label(e.ratio) == lb]) for lb in passed},
            "h2_felder_gesamt": H2_FIELDS_TOTAL}
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.research_lab.studies.s42")
    p.add_argument("step", choices=("count", "evaluate"))
    p.add_argument("--dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--fetch", action="store_true")
    a = p.parse_args(argv)
    folder, out_dir = a.dir.expanduser(), a.out.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.step == "evaluate" and not VERSION.startswith("1."):
        raise SystemExit("evaluate is locked while S42 is a draft")
    events: dict[str, dict[date, list[Event]]] = {k: {} for k in WINDOWS}
    results: dict[str, dict[str, dict]] = {k: {t: {} for t in s32.TARGETS} for k in WINDOWS}
    for day in s32.study_days():
        secs = s32.load_day(folder, day, fetch=a.fetch)
        for k, w in WINDOWS.items():
            chain = CONFIG.chain(w)
            evs = find_events(secs, day.isoformat(), chain)
            events[k][day] = evs
            if a.step == "evaluate":
                for t in s32.TARGETS:
                    results[k][t][day] = [(e, s32.outcome(secs, e, chain, target_kind=t)) for e in evs]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    report = {"studie": "S42", "version": VERSION, "config_sha256": CONFIG.digest(), "tage": len(s32.study_days())}
    if a.step == "count":
        report["zaehlung"] = {k: count(events[k]) for k in WINDOWS}
    else:
        report["auswertung"] = {k: {f"ziel_{t}": evaluate(results[k][t]) for t in s32.TARGETS} for k in WINDOWS}
    path = out_dir / f"s42_{a.step}_{stamp}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
