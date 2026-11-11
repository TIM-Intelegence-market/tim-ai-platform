"""S23: does open interest tell whether a broken swing level flips? (BTCUSDT, 1h, 2020-09 to 2024).

Rules: docs/research_lab/studien/S23_OPEN_INTEREST_AM_FLIP_PRAEREGISTRIERUNG_ENTWURF.md (draft 0.1).
Observation study without trades and without a register slot; the holdout from 2025-01-01 is never loaded.

    python -m src.research_lab.studies.s23 count    --root data/research_lab --out DIR [--fetch]
    python -m src.research_lab.studies.s23 evaluate --root data/research_lab --out DIR

Events and the flip label are S20's, unchanged (``s20.find_events``, ``s20.label``; S20 frozen as 1.0).
Like S21, one question against the mechanics model (distance of the close beyond the level): does open
interest add to it? S21 (frozen 1.0, failed) left open interest out because the archive was thought to start
in 12/2021; it starts on 2020-09-01 (``data.metrics``). One family, so no Holm correction (m = 1):

    O  open interest of the USD-M perpetual, in BTC: change over the 10 hours before the break, change in the
       break hour as a z-score against the 14 days before, and the level against the 14 days before

Extra criterion: the gain must also hold when the models learn only from training events from 2021-12 on, the
part of the archive Binance published at the time (2020-09 to 2021-11 was added in 2026).

``count`` is results-blind (events with full features, no label). ``evaluate`` refuses to run while
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

from src.research_lab.data.metrics import FIRST_DAY, MetricsRef, OpenInterest, days
from src.research_lab.studies import s20
from src.research_lab.studies.s20 import HOUR, Event

VERSION = "0.1"
SEED = 23
WINDOW = 10  # S20's training choice, as in S21; not chosen again
LOOKBACK_H = 336  # 14 days of hourly values for the two z-scores
MIN_LOOKBACK = 300  # at least this many of the 336 hourly values must exist
MAX_AGE_MS = 10 * 60_000  # an hourly value is the last snapshot at or before the hour, at most 10 minutes old
START_MS = int(datetime(2020, 9, 15, tzinfo=timezone.utc).timestamp() * 1000)  # 2020-09-01 plus the lookback
NATIVE_START_MS = int(datetime(2021, 12, 1, tzinfo=timezone.utc).timestamp() * 1000)  # first file not back-filled
LAST_DAY = date(2024, 12, 31)
FEATURES = ("oi_fenster", "oi_bruch_z", "oi_niveau_z")
MIN_EVENTS = {"training": 200, "validierung": 150}
MIN_NATIVE_TRAINING = 80
MIN_REL_GAIN = 0.01
ALPHA = 0.05
BOOT_DRAWS = 9_999
SHIFT_DRAWS = 199
MIN_SHIFT = 50


# -- features ------------------------------------------------------------------------------------------


class HourlyOI:
    """Open interest at full hours from 5-minute snapshots, without look-ahead: the value at hour ``t`` is the
    last snapshot with time <= t, and only if it is at most ``MAX_AGE_MS`` old. Nothing is filled."""

    def __init__(self, snapshots: Sequence[OpenInterest]) -> None:
        self.times = [s.time for s in snapshots]
        self.values = [s.contracts for s in snapshots]

    def at(self, t: int) -> float | None:
        i = bisect_right(self.times, t) - 1
        if i < 0 or t - self.times[i] > MAX_AGE_MS or self.values[i] <= 0:
            return None
        return self.values[i]


def _z(value: float, history: Sequence[float]) -> float:
    mean = sum(history) / len(history)
    sd = math.sqrt(sum((h - mean) ** 2 for h in history) / len(history))
    return (value - mean) / sd if sd > 1e-12 else 0.0


def oi_features(oi: HourlyOI, event: Event) -> tuple[float, float, float] | None:
    """(log change over the 10 hours before the break, break-hour log change as z against the 14 days of
    hourly log changes before it, log level at the break open as z against the 14 days before). Uses values up
    to the break close only. None when a needed value is missing or the history is too thin."""
    open_t, close_t = event.time, event.time + HOUR
    start, at_open, at_close = oi.at(open_t - WINDOW * HOUR), oi.at(open_t), oi.at(close_t)
    if start is None or at_open is None or at_close is None:
        return None
    levels = [oi.at(open_t - k * HOUR) for k in range(LOOKBACK_H, 0, -1)]
    changes = [math.log(b / a) for a, b in zip(levels, levels[1:]) if a is not None and b is not None]
    logs = [math.log(v) for v in levels if v is not None]
    if len(logs) < MIN_LOOKBACK or len(changes) < MIN_LOOKBACK - 1:
        return None
    return (math.log(at_open / start), _z(math.log(at_close / at_open), changes), _z(math.log(at_open), logs))


# -- rows ----------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Row:
    time: int
    week: int
    section: str
    y: int
    mechanics: float  # S20 "abstand_atr"
    oi: tuple[float, ...] | None


def build_rows(bars: Sequence, events: Sequence[Event], features: Mapping[int, tuple[float, ...]]) -> list[Row]:
    return [Row(e.time, s20.week_of(e.time), e.section, s20.label(bars, e),
                s20.candle_features(bars, e)[s20.MECHANICS_FEATURE], features.get(e.time) if e.time >= START_MS else None)
            for e in events]


def split(rows: Sequence[Row], *, native_only: bool = False) -> tuple[list[Row], list[Row]]:
    inside = [r for r in rows if r.time >= START_MS and r.oi is not None]
    train = [r for r in inside if r.section == "training" and (not native_only or r.time >= NATIVE_START_MS)]
    return train, [r for r in inside if r.section == "validierung"]


# -- model and checks ----------------------------------------------------------------------------------


def _predict(train: Sequence[Row], valid: Sequence[Row], with_oi: bool, yt: Sequence[int]) -> list[float]:
    def x(r: Row) -> list[float]:
        return [r.mechanics] + (list(r.oi) if with_oi else [])
    model = s20.fit([x(r) for r in train], yt)
    return [model.predict(x(r)) for r in valid]


def _gain(train: Sequence[Row], valid: Sequence[Row], yt: Sequence[int], yv: Sequence[int]) -> tuple[float, list[float], list[float]]:
    base = _predict(train, valid, False, yt)
    full = _predict(train, valid, True, yt)
    return s20.rel_gain(yv, full, base), base, full


def evaluate(rows: Sequence[Row], *, boot_draws: int = BOOT_DRAWS, shift_draws: int = SHIFT_DRAWS,
             version: str = VERSION) -> dict:
    if not version.startswith("1."):
        raise PermissionError("evaluate runs only after the rules are frozen as 1.0 (section 7)")
    train, valid = split(rows)
    gate = len(train) >= MIN_EVENTS["training"] and len(valid) >= MIN_EVENTS["validierung"]
    out: dict = {"merkmale": list(FEATURES), "ereignisse": {"training": len(train), "validierung": len(valid)},
                 "gate": gate}
    if not gate:
        return out | {"urteil": "nicht testbar (Gate)"}
    yt, yv = [r.y for r in train], [r.y for r in valid]
    observed, base, full = _gain(train, valid, yt, yv)
    diffs = [s20.log_loss(y, b) - s20.log_loss(y, f) for y, b, f in zip(yv, base, full)]
    p = s20.block_bootstrap_p([r.week for r in valid], diffs, seed="S23-O", draws=boot_draws)
    rng = random.Random(f"{SEED}:verschiebung")
    above = 0
    for _ in range(shift_draws):
        ot = rng.randint(MIN_SHIFT, len(yt) - MIN_SHIFT)
        ov = rng.randint(MIN_SHIFT, len(yv) - MIN_SHIFT)
        above += _gain(train, valid, yt[-ot:] + yt[:-ot], yv[-ov:] + yv[:-ov])[0] >= observed
    shift_p = (above + 1) / (shift_draws + 1)
    native, _ = split(rows, native_only=True)
    native_gain = _gain(native, valid, [r.y for r in native], yv)[0] if len(native) >= MIN_NATIVE_TRAINING else None
    checks = {"gewinn": observed >= MIN_REL_GAIN, "bootstrap": p is not None and p < ALPHA, "glueckstest": shift_p < ALPHA,
              "naht": native_gain is not None and native_gain > 0}
    out.update({"rel_gewinn": observed, "p": p, "glueckstest_p": shift_p, "training_ab_2021_12": len(native),
                "rel_gewinn_ab_2021_12": native_gain, "kriterien": checks,
                "auc_mechanik": s20.auc(yv, base), "auc_mit_oi": s20.auc(yv, full)})
    out["urteil"] = ("BESTANDEN (Kandidat)" if all(checks.values()) else
                     "NICHT BESTANDEN: Open Interest sagt den Flip nicht besser voraus als der Abstand zur Linie allein")
    return out


def count(events: Sequence[Event], drops: Mapping[str, int], covered: set[int]) -> dict:
    """Results-blind: events per section from START_MS and how many carry all features, no label."""
    per = {}
    for section in ("training", "validierung"):
        inside = [e for e in events if e.section == section and e.time >= START_MS]
        per[section] = {"ab_start": len(inside), "mit_merkmalen": sum(e.time in covered for e in inside)}
    native = sum(1 for e in events if e.section == "training" and e.time >= NATIVE_START_MS and e.time in covered)
    return {"verworfen": dict(sorted(drops.items())), "ereignisse": per, "training_ab_2021_12": native,
            "gate": per["training"]["mit_merkmalen"] >= MIN_EVENTS["training"]
            and per["validierung"]["mit_merkmalen"] >= MIN_EVENTS["validierung"],
            "naht_pruefbar": native >= MIN_NATIVE_TRAINING}


# -- data and CLI --------------------------------------------------------------------------------------


def refs() -> list[MetricsRef]:
    return [MetricsRef(d, symbol=s20.SYMBOL) for d in days(FIRST_DAY, LAST_DAY)]


def load_oi(root: Path, *, fetch: bool = False) -> tuple[HourlyOI, str, int]:
    from src.research_lab.data.store import ArchiveStore
    store = ArchiveStore(root)
    rs = refs()
    if fetch:
        for ref in rs:
            store.fetch(ref)
    snapshots = store.load_open_interest(rs)
    return HourlyOI(snapshots), store.dataset_hash(rs), len(snapshots)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s23")
    parser.add_argument("step", choices=("count", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fehlende Kerzen- und Metrics-Dateien laden (nur bis 2024-12)")
    args = parser.parse_args(argv)
    bars, digest = s20.load(args.root, fetch=args.fetch)
    oi, oi_digest, snapshots = load_oi(args.root, fetch=args.fetch)
    events, drops = s20.find_events(bars)
    features = {e.time: f for e in events if e.time >= START_MS and (f := oi_features(oi, e)) is not None}
    stamp = time.strftime("%Y-%m-%dT%H%MZ", time.gmtime())
    result = {"studie": "S23", "version": VERSION, "seed": SEED, "datensatz_sha256": digest, "kerzen": len(bars),
              "oi_datensatz_sha256": oi_digest, "oi_schnappschuesse": snapshots,
              "zaehllauf": count(events, drops, set(features))}
    if args.step == "evaluate":
        result["auswertung"] = evaluate(build_rows(bars, events, features))
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"s23_{args.step}_{stamp}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)
    print(json.dumps(result["zaehllauf"], ensure_ascii=False))
    if "auswertung" in result:
        print(result["auswertung"]["urteil"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
