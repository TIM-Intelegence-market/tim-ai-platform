"""S32: order book imbalance in a defended range ("path of least resistance"), BTCUSDT perpetual, Tardis free days.

Rules: docs/research_lab/studien/S32_ORDERBUCH_UNGLEICHGEWICHT_PRAEREGISTRIERUNG_ENTWURF.md (draft 0.2).
Data: Tardis.dev ``incremental_book_L2`` for Binance USDⓈ-M BTCUSDT, only the free first day of each month,
2020-06 to 2024-12 (``depth.tardis`` refuses other days and the holdout from 2025-01-01).

The trader's chain, all parameters fixed in :class:`Config`:

1. per second: mid and the book quantity within ±5 bp of the mid on each side (``LocalBook.band_qty``);
2. range: high and low of the mid over the last 15 minutes, width 20–60 bp;
3. both edges defended: each edge touched and left again by at least a quarter of the width, at least three
   touches in total;
4. position: mid in the lower quarter (long) or upper quarter (short) of the range;
5. book: the ratio own side / opposite side (bid/ask for long), as the lowest value of the last 3 seconds. There is
   no threshold: every ratio is recorded (Barti 13.11.2026: "alle Schiefwinkel ausprobieren");
6. outcome: entry one second later at the mid, target the middle of the range, stop 5 bp beyond the edge,
   at most 300 seconds.

H1 uses all ratios in ONE test: does the chance to reach the target first rise with the ratio (slope over the log
ratio)? One trend test instead of one test per threshold keeps the number of trials at one. H2 asks whether events
with a ratio of at least 2 (the video's range, fixed in advance) are positive after TIM costs. The table per ratio
bin is descriptive only.

``count`` is results-blind (event counts only). ``evaluate`` refuses to run while ``VERSION`` is a draft.
Stdlib only, plus the order book package.

    python -m src.research_lab.studies.s32 count    --dir ~/TIM-research/tardis --out DIR [--fetch]
    python -m src.research_lab.studies.s32 evaluate --dir ~/TIM-research/tardis --out DIR
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import random
from collections import deque
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from itertools import pairwise
from pathlib import Path

from src.research_lab.depth import tardis
from src.research_lab.depth.book import ASK, BID, SCALE, LocalBook
from src.research_lab.protocol import BASE_COSTS, STRESS_COSTS, CostModel

VERSION = "0.3"
SEED = 32
TRAINING_END = date(2022, 12, 31)
MIN_EVENTS = 300  # per section, all ratios, else "nicht prüfbar"
MIN_H2 = 100  # per section, ratio >= Config.ratio
RATIO_CAP = 100.0  # an empty opposite side counts as 100:1
BINS = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, float("inf"))
BOOT_DRAWS = 9_999
ALPHA = 0.05


@dataclass(frozen=True)
class Config:
    band_bp: int = 5  # P1: book quantity within ±5 bp of the mid
    ratio: float = 2.0  # H2 group: own side at least twice the opposite side (bins are descriptive)
    hold_s: int = 3  # P3: imbalance held without interruption
    window_s: int = 900  # P4: range window, 15 minutes
    width_min_bp: float = 20.0  # P5
    width_max_bp: float = 60.0
    touch_zone: float = 0.10  # P6: a touch = mid within 10 % of the width from the edge
    rebound: float = 0.25  # P6: left again = moved at least 25 % of the width away from the edge
    min_touches: int = 3  # P6: both edges together
    position: float = 0.25  # P7: lower / upper quarter of the range
    min_valid_share: float = 0.95  # window must have a valid book in at least 95 % of its seconds
    entry_delay_s: int = 1  # P9
    stop_bp: float = 5.0  # P9: beyond the edge
    horizon_s: int = 300  # P9
    cooldown_s: int = 300  # one event per 300 s, so outcome windows do not overlap

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


CONFIG = Config()


@dataclass(frozen=True)
class Second:
    mid: float  # USDT
    bid_q: float  # BTC within the band below the mid
    ask_q: float  # BTC within the band above the mid


@dataclass(frozen=True)
class Event:
    day: str
    i: int  # second of the day (UTC)
    side: int  # +1 long, -1 short
    ratio: float  # own side / opposite side, lowest value of the last hold_s seconds
    lo: float
    hi: float


# -- per-second book ---------------------------------------------------------------------------------------


def seconds_from_book_csv(path: Path, day: date, cfg: Config = CONFIG) -> list[Second | None]:
    """Dense list of 86 400 seconds (UTC day): the book at the end of each second, None where it is not usable.

    Rows are applied in file order (Tardis sorts by local receive time). A new snapshot block clears the book; the
    book is usable from the first non-snapshot row after it. A crossed or one-sided book gives None.
    """
    tardis.check_day(day)
    start_us = int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()) * 1_000_000
    out: list[Second | None] = [None] * 86_400
    book = LocalBook()
    in_snapshot, usable, cur = False, False, -1

    def state() -> Second | None:
        if not usable:
            return None
        q = book.band_qty(cfg.band_bp)
        m2 = book.mid2()
        if q is None or m2 is None:
            return None
        return Second(mid=m2 / 2 / SCALE, bid_q=q[0] / SCALE, ask_q=q[1] / SCALE)

    with gzip.open(path, "rt", newline="") as fh:
        for r in csv.DictReader(fh):
            sec = (int(r["local_timestamp"]) - start_us) // 1_000_000
            if sec != cur and 0 <= cur < 86_400:
                s = state()
                for k in range(cur, min(max(sec, cur + 1), 86_400)):
                    out[k] = s
            cur = max(cur, sec)
            snap = r["is_snapshot"] == "true"
            if snap and not in_snapshot:
                book.clear()
                usable = False
            elif not snap and in_snapshot:
                usable = True
            in_snapshot = snap
            book.set(BID if r["side"] == "bid" else ASK, r["price"], r["amount"])
    if 0 <= cur < 86_400:
        out[cur] = state()
    return out


# -- chain -------------------------------------------------------------------------------------------------


def defended(window: Sequence[float], lo: float, hi: float, cfg: Config = CONFIG) -> bool:
    """Both edges touched and left again (P6), at least ``min_touches`` touches in total."""
    width = hi - lo

    def edge(dist: Iterator[float]) -> tuple[int, int]:
        armed, pending, touches, rebounds = True, False, 0, 0
        for d in dist:  # d = distance from the edge in units of the width
            if armed and d <= cfg.touch_zone:
                touches += 1
                armed, pending = False, True
            elif not armed and d >= cfg.rebound:
                armed = True
                if pending:
                    rebounds += 1
                    pending = False
        return touches, rebounds

    t_lo, r_lo = edge((m - lo) / width for m in window)
    t_hi, r_hi = edge((hi - m) / width for m in window)
    return r_lo >= 1 and r_hi >= 1 and t_lo + t_hi >= cfg.min_touches


def side_ratio(s: Second, side: int) -> float | None:
    """Own side / opposite side (bid/ask for long, ask/bid for short); None for an empty book in the band."""
    own, opp = (s.bid_q, s.ask_q) if side > 0 else (s.ask_q, s.bid_q)
    if own <= 0 and opp <= 0:
        return None
    return RATIO_CAP if opp <= 0 else min(own / opp, RATIO_CAP)


def find_events(secs: Sequence[Second | None], day: str, cfg: Config = CONFIG) -> list[Event]:
    """Events of one day, every ratio. The first ``window_s`` seconds of a day are warm-up."""
    events: list[Event] = []
    last = -10**9
    lo_q: deque[tuple[int, float]] = deque()
    hi_q: deque[tuple[int, float]] = deque()
    valid_in_window = 0
    for i, s in enumerate(secs):
        if i - cfg.window_s >= 0 and secs[i - cfg.window_s] is not None:
            valid_in_window -= 1
        while lo_q and lo_q[0][0] <= i - cfg.window_s:
            lo_q.popleft()
        while hi_q and hi_q[0][0] <= i - cfg.window_s:
            hi_q.popleft()
        if s is None:
            continue
        valid_in_window += 1
        while lo_q and lo_q[-1][1] >= s.mid:
            lo_q.pop()
        lo_q.append((i, s.mid))
        while hi_q and hi_q[-1][1] <= s.mid:
            hi_q.pop()
        hi_q.append((i, s.mid))
        if i < cfg.window_s or i - last < cfg.cooldown_s or valid_in_window < cfg.min_valid_share * cfg.window_s:
            continue
        lo, hi = lo_q[0][1], hi_q[0][1]
        width_bp = (hi - lo) / s.mid * 10_000
        if not cfg.width_min_bp <= width_bp <= cfg.width_max_bp:
            continue
        pos = (s.mid - lo) / (hi - lo)
        want = 1 if pos <= cfg.position else (-1 if pos >= 1 - cfg.position else 0)
        if want == 0:
            continue
        recent = secs[i - cfg.hold_s + 1: i + 1]
        if any(x is None for x in recent):
            continue
        ratios = [side_ratio(x, want) for x in recent]
        if any(r is None for r in ratios):
            continue
        window = [x.mid for x in secs[i - cfg.window_s + 1: i + 1] if x is not None]
        if not defended(window, lo, hi, cfg):
            continue
        last = i
        events.append(Event(day=day, i=i, side=want, ratio=min(ratios), lo=lo, hi=hi))
    return events


def bin_label(r: float) -> str:
    for lo, hi in pairwise(BINS):
        if lo <= r < hi:
            return f"{lo:g}-{hi:g}" if hi != float("inf") else f">={lo:g}"
    return f">={BINS[-2]:g}"


# -- outcome -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Outcome:
    exit: str  # target / stop / time / missing / no_room
    gross_bp: float
    risk_bp: float


def outcome(secs: Sequence[Second | None], ev: Event, cfg: Config = CONFIG) -> Outcome:
    j0 = ev.i + cfg.entry_delay_s
    if j0 >= len(secs) or secs[j0] is None:
        return Outcome("missing", 0.0, 0.0)
    entry = secs[j0].mid
    target = (ev.lo + ev.hi) / 2
    stop = ev.lo * (1 - cfg.stop_bp / 10_000) if ev.side > 0 else ev.hi * (1 + cfg.stop_bp / 10_000)
    if (target - entry) * ev.side <= 0 or (entry - stop) * ev.side <= 0:
        return Outcome("no_room", 0.0, 0.0)
    risk_bp = abs(entry - stop) / entry * 10_000
    last_mid = entry
    for j in range(j0 + 1, min(j0 + cfg.horizon_s, len(secs) - 1) + 1):
        s = secs[j]
        if s is None:
            continue
        last_mid = s.mid
        if (s.mid - target) * ev.side >= 0:
            return Outcome("target", (target - entry) / entry * 10_000 * ev.side, risk_bp)
        if (s.mid - stop) * ev.side <= 0:
            return Outcome("stop", (stop - entry) / entry * 10_000 * ev.side, risk_bp)
    if j0 + cfg.horizon_s >= len(secs):
        return Outcome("missing", 0.0, 0.0)  # cut by the end of the day file
    return Outcome("time", (last_mid - entry) / entry * 10_000 * ev.side, risk_bp)


def net_r(o: Outcome, costs: CostModel = BASE_COSTS) -> float:
    """Net result in R (risk = distance to the stop), protocol 1.3 costs as fractions of price per side."""
    cost_bp = (2 * costs.fee + costs.slippage + (costs.stop_slippage if o.exit == "stop" else 0.0)) * 10_000
    return (o.gross_bp - cost_bp) / o.risk_bp


# -- days, count, evaluate ---------------------------------------------------------------------------------


def study_days() -> list[date]:
    out, y, m = [], 2020, 6
    while date(y, m, 1) < tardis.HOLDOUT_START:
        out.append(date(y, m, 1))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def section(day: date) -> str:
    return "training" if day <= TRAINING_END else "validierung"


def load_day(folder: Path, day: date, *, fetch: bool) -> list[Second | None]:
    path = folder / f"incremental_book_L2_{day.isoformat()}_BTCUSDT.csv.gz"
    if not path.exists():
        if not fetch:
            raise FileNotFoundError(path)
        path = tardis.download("incremental_book_L2", day, folder)
    return seconds_from_book_csv(path, day)


def count(events_by_day: dict[date, list[Event]], cfg: Config = CONFIG) -> dict:
    """Results-blind: events per section, ratio bin and side, and per day. No outcome is computed."""
    out: dict = {"training": {}, "validierung": {}, "je_tag": {}}
    for day, evs in sorted(events_by_day.items()):
        sec = out[section(day)]
        for e in evs:
            key = f"{bin_label(e.ratio)}_{'long' if e.side > 0 else 'short'}"
            sec[key] = sec.get(key, 0) + 1
        out["je_tag"][day.isoformat()] = len(evs)
    for name in ("training", "validierung"):
        evs = [e for d, es in events_by_day.items() if section(d) == name for e in es]
        out[name]["alle"] = len(evs)
        out[name]["ab_schwelle"] = sum(e.ratio >= cfg.ratio for e in evs)
        out[name]["pruefbar"] = len(evs) >= MIN_EVENTS and out[name]["ab_schwelle"] >= MIN_H2
    return out


def _log_ratio(r: float) -> float:
    return math.log(min(max(r, 0.1), 10.0))  # clipped to 1:10 ... 10:1 so a few extremes do not dominate


def slope(rows: Sequence[tuple[float, Outcome]]) -> float | None:
    """OLS slope of "target first" (0/1) on the clipped log ratio."""
    if len(rows) < 3:
        return None
    xs = [_log_ratio(r) for r, _ in rows]
    ys = [1.0 if o.exit == "target" else 0.0 for _, o in rows]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx


def _boot_lower(days: list[list[tuple[float, Outcome]]], stat, draws: int, rng: random.Random) -> float:
    """One-sided lower (1 − ALPHA/2) bound of ``stat``, days resampled with replacement (block bootstrap)."""
    vals = []
    for _ in range(draws):
        sample = [r for _ in days for r in days[rng.randrange(len(days))]]
        v = stat(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    return vals[int(ALPHA / 2 * len(vals))] if vals else float("nan")  # Bonferroni over H1, H2 (m = 2)


def evaluate(results: dict[date, list[tuple[Event, Outcome]]], *, version: str = VERSION,
             draws: int = BOOT_DRAWS, cfg: Config = CONFIG) -> dict:
    if not version.startswith("1."):
        raise PermissionError("evaluate runs only after the rules are frozen as 1.0 (section 8)")
    rng = random.Random(SEED)
    out: dict = {}
    for name in ("training", "validierung"):
        days = [[(e.ratio, o) for e, o in rs if o.exit in ("target", "stop", "time")]
                for d, rs in sorted(results.items()) if section(d) == name]
        days = [d for d in days if d]
        flat = [r for d in days for r in d]

        def mean_net(rows, costs=BASE_COSTS):
            xs = [net_r(o, costs) for r, o in rows if r >= cfg.ratio]
            return sum(xs) / len(xs) if xs else None

        bins: dict[str, dict] = {}
        for r, o in flat:
            b = bins.setdefault(bin_label(r), {"n": 0, "ziel": 0, "netto_r": 0.0})
            b["n"] += 1
            b["ziel"] += o.exit == "target"
            b["netto_r"] += net_r(o)
        for b in bins.values():
            b["ziel_zuerst"] = b.pop("ziel") / b["n"]
            b["netto_r"] /= b["n"]
        n_h2 = sum(r >= cfg.ratio for r, _ in flat)
        out[name] = {
            "alle": len(flat), "ab_schwelle": n_h2, "pruefbar": len(flat) >= MIN_EVENTS and n_h2 >= MIN_H2,
            "h1_steigung": slope(flat), "h1_untere_grenze": _boot_lower(days, slope, draws, rng),
            "h2_netto_r": mean_net(flat), "h2_untere_grenze": _boot_lower(days, mean_net, draws, rng),
            "h2_netto_r_stress": mean_net(flat, STRESS_COSTS), "je_verhaeltnis": dict(sorted(bins.items())),
        }
    t, v = out["training"], out["validierung"]
    ok = t["pruefbar"] and v["pruefbar"]
    out["h1_bestanden"] = bool(ok and t["h1_untere_grenze"] > 0 and v["h1_untere_grenze"] > 0)
    out["h2_bestanden"] = bool(ok and t["h2_untere_grenze"] > 0 and v["h2_untere_grenze"] > 0)
    return out


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.research_lab.studies.s32")
    p.add_argument("step", choices=("count", "evaluate"))
    p.add_argument("--dir", type=Path, required=True, help="folder with the Tardis day files")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--fetch", action="store_true", help="download missing free days")
    a = p.parse_args(argv)
    folder, out_dir = a.dir.expanduser(), a.out.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.step == "evaluate" and not VERSION.startswith("1."):
        raise SystemExit("evaluate is locked while S32 is a draft (section 8)")
    events: dict[date, list[Event]] = {}
    results: dict[date, list[tuple[Event, Outcome]]] = {}
    for day in study_days():
        secs = load_day(folder, day, fetch=a.fetch)
        evs = find_events(secs, day.isoformat())
        events[day] = evs
        if a.step == "evaluate":
            results[day] = [(e, outcome(secs, e)) for e in evs]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    report = {"studie": "S32", "version": VERSION, "config_sha256": CONFIG.digest(), "config": asdict(CONFIG),
              "tage": len(events)}
    report["zaehlung" if a.step == "count" else "auswertung"] = (
        count(events) if a.step == "count" else evaluate(results))
    path = out_dir / f"s32_{a.step}_{stamp}.json"
    path.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
