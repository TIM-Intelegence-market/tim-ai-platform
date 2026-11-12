"""S28 (draft): positioning from the Binance "metrics" archive (open interest, top-trader ratio, taker ratio) on the S27 trade.

Rules: docs/research_lab/studien/S28_POSITIONIERUNG_METRICS_PRAEREGISTRIERUNG_ENTWURF.md (version 0.1). Source: S24, S26 and S27 found no edge
in the indicators TIM had on 1h BTC; the next try needs data TIM never used. Uzi said "S28" on 12.11.2026 after the
data question. The holdout from 2025-01-01 is never loaded (the metrics refs are fetched only up to 2024-12-31).

    python -m src.research_lab.studies.s28 count --root data/research_lab --out DIR [--fetch] [--workers N]

This step is results-blind: moments, feature coverage and complete rows per section. No outcome is read. ``evaluate`` is
not built yet; it is added together with the freeze (version 1.0) and refuses a draft.

Family O (one new family, three features, sign = +1 for LONG, -1 for SHORT, read at the close of the 1h candle):

    oi_preis   sign * sign(price change over 24 h) * relative open interest change over 24 h
    top_ls     sign * ln(sum_toptrader_long_short_ratio)
    taker_ls   sign * ln(mean sum_taker_long_short_vol_ratio of the last 12 snapshots, one hour)

No look-ahead: only snapshots stamped at least ``LAG_MS`` (5 min) before the close count, because the archive does not
say whether a stamp marks the start or the end of its 5-minute period (the S12 lesson).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import time
from bisect import bisect_right
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from src.research_lab.data.metrics import FIRST_DAY, MetricsRef, days
from src.research_lab.data.parse import Kline, read_single_csv
from src.research_lab.protocol import HOLDOUT_START_MS
from src.research_lab.studies import s22, s24
from src.research_lab.studies.s20 import HOUR, atr_series, week_of

VERSION = "0.1"
SEED = 28
FAMILY = "O"
FEATURES = ("oi_preis", "top_ls", "taker_ls")
LAG_MS = 5 * 60_000
STEP_MS = 5 * 60_000
DAY_MS = 24 * HOUR
TOLERANCE_MS = 15 * 60_000  # the snapshot 24 h back may be at most this far from its exact time
TAKER_SNAPSHOTS = 12
LAST_DAY = date(2024, 12, 31)  # never loads the holdout
MIN_TRADES = s24.MIN_TRADES
MIN_WEEKS = s24.MIN_WEEKS
COLUMNS = ("create_time", "symbol", "sum_open_interest", "sum_open_interest_value", "count_toptrader_long_short_ratio",
           "sum_toptrader_long_short_ratio", "count_long_short_ratio", "sum_taker_long_short_vol_ratio")


@dataclass(frozen=True, slots=True)
class Snapshots:
    times: list[int]
    oi: list[float]
    top: list[float]
    taker: list[float]


def _to_ms(value: str) -> int:
    return int(datetime.strptime(value.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp() * 1000)


def parse_snapshots(text: str) -> dict[int, tuple[float, float, float]]:
    """time -> (open interest in BTC, top-trader position ratio, taker volume ratio). Identical repeats collapse, two
    different rows for one time are an error (nothing is guessed)."""
    out: dict[int, tuple[float, float, float]] = {}
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0].strip() == COLUMNS[0]:
            continue
        if len(row) < len(COLUMNS):
            raise ValueError("metrics row has fewer columns than the header")
        values = (float(row[2]), float(row[5]), float(row[7]))
        t = _to_ms(row[0])
        if t in out and out[t] != values:
            raise ValueError(f"two different metrics rows for one snapshot ({row[0]})")
        out[t] = values
    return out


def load_snapshots(root: Path, *, fetch: bool = False, workers: int = 1, last: date = LAST_DAY) -> Snapshots:
    from src.research_lab.data.store import ArchiveStore

    store = ArchiveStore(root)
    refs = [MetricsRef(d) for d in days(FIRST_DAY, last)]
    if fetch:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(store.fetch, refs))
    merged: dict[int, tuple[float, float, float]] = {}
    for ref in refs:
        try:
            text = store._verified_csv(ref, None)  # noqa: SLF001 - the shared checksum + holdout guard
        except FileNotFoundError:
            continue  # a missing day leaves a gap; coverage in ``count`` shows it
        merged.update(parse_snapshots(text))
    times = sorted(merged)
    return Snapshots(times, [merged[t][0] for t in times], [merged[t][1] for t in times], [merged[t][2] for t in times])


def features(snap: Snapshots, bars: Sequence[Kline], i: int, sign: float) -> tuple[float, ...] | None:
    """Family O at the close of ``bars[i]``; None when a needed snapshot is missing or not positive."""
    close_time = bars[i].open_time + HOUR
    k = bisect_right(snap.times, close_time - LAG_MS) - 1
    if k < TAKER_SNAPSHOTS or close_time - LAG_MS - snap.times[k] > TOLERANCE_MS or i < 24:
        return None
    back = bisect_right(snap.times, snap.times[k] - DAY_MS) - 1
    if back < 0 or abs(snap.times[k] - DAY_MS - snap.times[back]) > TOLERANCE_MS:
        return None
    window = snap.taker[k - TAKER_SNAPSHOTS + 1:k + 1]
    if snap.times[k] - snap.times[k - TAKER_SNAPSHOTS + 1] > (TAKER_SNAPSHOTS + 2) * STEP_MS:
        return None
    if snap.oi[back] <= 0 or snap.top[k] <= 0 or min(window) <= 0:
        return None
    change = bars[i].close - bars[i - 24].close
    direction = (change > 0) - (change < 0)
    return (sign * direction * (snap.oi[k] / snap.oi[back] - 1.0),
            sign * math.log(snap.top[k]),
            sign * math.log(sum(window) / len(window)))


def build_rows(snap: Snapshots, bars_1h: Sequence[Kline]) -> list[s24.Row]:
    atrs = atr_series(bars_1h)
    rows = []
    for i in s22.moments(bars_1h, atrs):
        close_time = bars_1h[i].open_time + HOUR
        section = s22.section_of(close_time)
        for direction in s22.DIRECTIONS:
            sign = 1.0 if direction == "LONG" else -1.0
            rows.append(s24.Row(close_time, section, direction, {FAMILY: features(snap, bars_1h, i, sign)}))
    return rows


def count(rows: Sequence[s24.Row]) -> dict:
    """Results-blind: moments, coverage and complete rows per section, and the gate (as S24)."""
    out: dict = {}
    for name in s22.SECTIONS:
        part = [r for r in rows if r.section == name]
        full = [r for r in part if r.features.get(FAMILY) is not None]
        per_dir = {d: sum(1 for r in full if r.direction == d) for d in s22.DIRECTIONS}
        out[name] = {"momente": len({r.time for r in part}), "zeilen": len(part), "abdeckung": len(full),
                     "vollstaendig_je_richtung": per_dir, "wochen": len({week_of(r.time) for r in full}),
                     "gate": min(per_dir.values(), default=0) >= MIN_TRADES}
    out["gate"] = all(out[n]["gate"] for n in s22.SECTIONS) and out["validierung"]["wochen"] >= MIN_WEEKS
    return out


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="s28")
    parser.add_argument("step", choices=("count", "evaluate"))
    parser.add_argument("--root", type=Path, default=Path("data/research_lab"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fetch", action="store_true", help="fehlende Tagesdateien laden (nur bis 2024-12-31)")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    if args.step == "evaluate":
        raise SystemExit(f"S28 {VERSION} ist ein Entwurf: evaluate entsteht mit dem Einfrieren als 1.0")
    bars_1h, _bars_30m, digest = s22.load(args.root, fetch=args.fetch)
    snap = load_snapshots(args.root, fetch=args.fetch, workers=args.workers)
    rows = build_rows(snap, bars_1h)
    result = {"studie": "S28", "version": VERSION, "seed": SEED, "datensatz_sha256": digest,
              "merkmale": {FAMILY: list(FEATURES)}, "snapshots": len(snap.times),
              "erster_stand": snap.times[0] if snap.times else None, "letzter_stand": snap.times[-1] if snap.times else None,
              "zaehllauf": count(rows)}
    assert max(snap.times, default=0) < HOLDOUT_START_MS, "holdout data loaded"
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"s28_count_{time.strftime('%Y-%m-%dT%H%MZ', time.gmtime())}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(path)
    print(json.dumps(result["zaehllauf"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
