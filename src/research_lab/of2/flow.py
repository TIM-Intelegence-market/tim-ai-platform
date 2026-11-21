"""Candle framing, change of flow and delta peak (Fabervaale video 16.11.2026, plan packages P1 and P2).

Building blocks only: nothing here emits a signal or changes OF2 1.0. A later model (M8, plan package P3) may use them.
Everything is read from footprints of *closed* candles (past-only, see ``footprint.py``).

- ``candle_profile``: volume profile of one candle or of several merged candles (POC, VAL, VAH; 70 % rule as S8).
- ``flow_state``: change of flow from the POC path of the last two candles (video W14):
  POC lower = sellers lead; POC higher and the close above the previous candle's VAH = shift to buyers (mirror for
  sellers). A higher (lower) POC without acceptance beyond the previous value stays ``KAEUFER`` (``VERKAEUFER``).
- ``delta_peak``: price bin with the largest net aggressive delta in the trade direction over an impulse A->B
  (video W8: "where the buyers were mainly aggressive"; the stop goes beyond it).
- ``void_ratio``: mean volume per bin between two prices against the mean per bin of the whole range; small means
  thin volume on the way (video W7: room to the next node).

    python -m src.research_lab.of2.flow --bars <orderflow_ml root> --out DIR [--workers 16]

counts, results-blind and on training days only (as ``calibrate.py``), how often each flow state fires on the
15m candles and how far the delta peak of a candle lies from its close. No price outcome is read.
"""
from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from multiprocessing import Pool
from pathlib import Path

from src.research_lab.of2.candles import Candle, CandleBuilder
from src.research_lab.of2.config import DEFAULT_CONFIG, Config
from src.research_lab.of2.footprint import DayFootprints, Footprint
from src.research_lab.orderflow_ml.profile import value_area

STATES = ("WECHSEL_HOCH", "WECHSEL_TIEF", "KAEUFER", "VERKAEUFER", "NEUTRAL")


@dataclass(frozen=True, slots=True)
class CandleProfile:
    poc: float   # centre of the POC bin
    val: float   # lower edge of the value area
    vah: float   # upper edge of the value area


def merge_footprints(fps: Sequence[Footprint]) -> dict[int, tuple[int, int]]:
    """Buy and sell volume per merged bin over several footprints of one day (same bin width)."""
    steps = {fp.step for fp in fps if not fp.empty}
    if len(steps) > 1:
        raise ValueError("footprints with different bin widths cannot be merged")
    acc: dict[int, list[int]] = {}
    for fp in fps:
        for b, buy, sell in fp.bins:
            cell = acc.setdefault(b, [0, 0])
            cell[0] += buy
            cell[1] += sell
    return {b: (v[0], v[1]) for b, v in acc.items()}


def _step(fps: Sequence[Footprint]) -> float | None:
    return next((fp.step for fp in fps if not fp.empty), None)


def candle_profile(fps: Footprint | Sequence[Footprint]) -> CandleProfile | None:
    """POC/VAL/VAH of one footprint or of several merged ones; None without volume."""
    seq = [fps] if isinstance(fps, Footprint) else list(fps)
    step = _step(seq)
    if step is None:
        return None
    va = value_area({b: buy + sell for b, (buy, sell) in merge_footprints(seq).items()})
    if va is None:
        return None
    poc, lo, hi = va
    return CandleProfile((poc + 0.5) * step, lo * step, (hi + 1) * step)


def flow_state(prev: CandleProfile | None, last: CandleProfile | None, last_close: float) -> str:
    """Change of flow between two consecutive candle profiles (W14). ``NEUTRAL`` when a profile is missing or the
    POC did not move."""
    if prev is None or last is None or last.poc == prev.poc:
        return "NEUTRAL"
    if last.poc > prev.poc:
        return "WECHSEL_HOCH" if last_close > prev.vah else "KAEUFER"
    return "WECHSEL_TIEF" if last_close < prev.val else "VERKAEUFER"


def delta_peak(fps: Sequence[Footprint], direction: int) -> float | None:
    """Centre of the bin with the largest net delta in ``direction`` (+1: buy - sell, -1: sell - buy) over the
    merged footprints; None when no bin has a positive net delta that way. Ties: the bin nearest the start of the
    move (lowest for a long, highest for a short), so the stop sits beyond the earliest defence."""
    step = _step(fps)
    if step is None:
        return None
    best: tuple[int, int] | None = None   # (net, bin)
    for b, (buy, sell) in sorted(merge_footprints(fps).items(), reverse=direction < 0):
        net = (buy - sell) * direction
        if net > 0 and (best is None or net > best[0]):
            best = (net, b)
    return None if best is None else (best[1] + 0.5) * step


def void_ratio(fps: Sequence[Footprint], lo: float, hi: float) -> float | None:
    """Mean volume per bin with its centre in [lo, hi] / mean volume per bin of the merged range. Bins without prints
    inside the range count as zero. None without volume or without a bin in [lo, hi]."""
    step = _step(fps)
    if step is None or hi < lo:
        return None
    merged = merge_footprints(fps)
    if not merged:
        return None
    first, last = min(merged), max(merged)
    vols = {b: sum(merged.get(b, (0, 0))) for b in range(first, last + 1)}
    total = sum(vols.values())
    if total <= 0:
        return None
    inside = [v for b, v in vols.items() if lo <= (b + 0.5) * step <= hi]
    if not inside:
        return None
    return (sum(inside) / len(inside)) / (total / len(vols))


# -- results-blind frequencies on training days -------------------------------------------------------------------
def count_day(bars, profile, cfg: Config) -> dict:
    """Flow states of consecutive readable 15m candles and the delta-peak distance from the close (share of price)."""
    out: dict = {"paare": 0, "zustand": dict.fromkeys(STATES, 0), "peak_n": 0, "peak_abstand_bp": {}}
    first_price = next((b.first_price_e8 / 1e8 for b in bars if b.has_trades), 0.0)
    fps = DayFootprints(profile, cfg.fp_step_pct, first_price)
    builder = CandleBuilder(cfg.tf_sfp)
    prev: CandleProfile | None = None
    for bar in bars:
        c: Candle | None = builder.push(bar)
        if c is None:
            continue
        fp = fps.candle(c.start, c.minutes)
        if not c.has_trades or fp.n_bins < cfg.fp_min_bins:
            prev = None
            continue
        last = candle_profile(fp)
        if prev is not None:
            out["paare"] += 1
            out["zustand"][flow_state(prev, last, c.close)] += 1
        direction = 1 if c.close >= c.open else -1
        peak = delta_peak([fp], direction)
        if peak is not None and c.close > 0:
            out["peak_n"] += 1
            bucket = str(min(50, int(abs(c.close - peak) / c.close * 10_000) // 5 * 5))   # 5-bp buckets, 50 = 50+
            out["peak_abstand_bp"][bucket] = out["peak_abstand_bp"].get(bucket, 0) + 1
        prev = last
    return out


def _add(acc: dict, part: dict) -> dict:
    for k, v in part.items():
        if isinstance(v, dict):
            _add(acc.setdefault(k, {}), v)
        else:
            acc[k] = acc.get(k, 0) + v
    return acc


def _chunk(args: tuple) -> dict:
    from src.research_lab.orderflow_ml.store import MinuteBarStore
    root, days = args
    store, acc = MinuteBarStore(root), {}
    for day in days:
        _add(acc, count_day(store.load(day), store.load_profile(day), DEFAULT_CONFIG))
    return acc


def report(totals: dict) -> str:
    n = totals.get("paare", 0) or 1
    lines = ["# Kerzenprofil und Flow-Wechsel, Training (nur Häufigkeiten)", "",
             f"Paare lesbarer 15m-Kerzen: {totals.get('paare', 0)}. Ziel aus dem Plan: kein Zustand über 40 %.", "",
             "| Zustand | Anteil |", "|---|---|"]
    lines += [f"| {k} | {totals['zustand'].get(k, 0) / n:.1%} |" for k in STATES]
    pn = totals.get("peak_n", 0) or 1
    lines += ["", "## Abstand Delta-Spitze zum Schluss (Basispunkte)", "", "| ab bp | Anteil |", "|---|---|"]
    lines += [f"| {k} | {v / pn:.1%} |" for k, v in sorted(totals.get("peak_abstand_bp", {}).items(), key=lambda kv: int(kv[0]))]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    from src.research_lab.orderflow_ml.store import MinuteBarStore
    parser = argparse.ArgumentParser(prog="python -m src.research_lab.of2.flow")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args(argv)
    cfg = DEFAULT_CONFIG
    first, last = date.fromisoformat(cfg.first_day), date.fromisoformat(cfg.training_end)   # training only
    present = set(MinuteBarStore(args.bars).present_days())
    days = [d for d in (first + timedelta(days=i) for i in range((last - first).days + 1)) if d in present]
    workers = max(1, min(args.workers, len(days)))
    chunks = [(args.bars, days[i::workers]) for i in range(workers)]
    if workers > 1:
        with Pool(workers) as pool:
            parts = pool.map(_chunk, chunks)
    else:
        parts = [_chunk(chunks[0])] if days else []
    totals: dict = {"paare": 0, "zustand": dict.fromkeys(STATES, 0), "peak_n": 0, "peak_abstand_bp": {}}
    for part in parts:
        _add(totals, part)
    totals.update({"tage": len(days), "erster_tag": first.isoformat(), "letzter_tag": last.isoformat()})
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "of2_flow.json").write_text(json.dumps(totals, indent=1, sort_keys=True) + "\n")
    (args.out / "of2_flow.md").write_text(report(totals))
    print(json.dumps(totals["zustand"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
