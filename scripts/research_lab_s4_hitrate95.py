"""Study S4 follow-up, exploratory (NOT confirmatory): what target distance gives a 95 % hit
rate for the frozen S4 entries, and does any such setting earn money after costs?

    python scripts/research_lab_s4_hitrate95.py --out DIR

Uzi asked on 2026-10-25 to raise the hit-rate goal to 95 %. A hit rate can always be
pushed up by shrinking the target (and widening the stop), so the honest question is
whether the entries keep a positive expectancy once the target is small enough for
95 %. This script keeps the S4 entry rules and time stop, re-runs each variant over a
grid of target distances (in R) and stop widths (multiples of the frozen S4 stop), and
reports hit rate and E[R] per cell. Signals are computed once per variant and
replayed, so the entries are identical in every cell. Holdout 2025+ is never read.
Reference: for a driftless random walk without costs the chance to hit +T R before
-1 R is 1 / (1 + T); 95 % needs T <= 0.0526 R.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.research_lab.backtest.engine import History, Signal, run_backtest  # noqa: E402
from src.research_lab.data.archive import Dataset  # noqa: E402
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore  # noqa: E402
from src.research_lab.hypotheses import s4  # noqa: E402
from src.research_lab.protocol import BASE_COSTS, HOLDOUT_START_MS  # noqa: E402

import research_lab_s4 as base  # noqa: E402
from research_lab_s4_explore import summarize  # noqa: E402

H = 3_600_000
TARGETS = (0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.75)
STOP_MULTIPLIERS = (1.0, 2.0, 4.0)
GOAL = 0.95


def collect(bars, strategy, start_ms: int, end_ms: int) -> dict[int, tuple[Signal, float]]:
    """Signals of the frozen strategy by bar index, with the signal bar's close."""
    out: dict[int, tuple[Signal, float]] = {}
    for t, bar in enumerate(bars):
        if bar.open_time < start_ms:
            continue
        if bar.open_time >= end_ms:
            break
        signal = strategy(History(bars, t))
        if signal is not None:
            out[t] = (signal, bar.close)
    return out


def replay(signals: dict[int, tuple[Signal, float]], target_r: float, stop_mult: float):
    def strategy(history: History) -> Signal | None:
        found = signals.get(len(history) - 1)
        if found is None:
            return None
        signal, close = found
        stop = close - stop_mult * (close - signal.stop)
        return Signal(signal.side, stop, target_r=target_r, time_stop_bars=signal.time_stop_bars)
    return strategy


def explore(store: ArchiveStore, out_dir: Path) -> int:
    data = {}
    for symbol, (_, start) in base.SYMBOLS.items():
        hourly = [b for b in store.load_klines(base.refs(symbol, Dataset.KLINES, "1h")) if b.open_time < HOLDOUT_START_MS]
        daily = [b for b in store.load_klines(base.refs(symbol, Dataset.KLINES, "1d")) if b.open_time < HOLDOUT_START_MS]
        funding = [f for f in store.load_funding(base.refs(symbol, Dataset.FUNDING, None)) if f.time < HOLDOUT_START_MS]
        data[symbol] = (hourly, daily, funding, base._utc_ms(start[0], start[1], 1))
    payload: dict = {"study": "S4 follow-up 95 %", "kind": "EXPLORATORY, not confirmatory; holdout untouched",
                     "commit": base._commit(), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "costs": "BASE_COSTS", "targets_r": TARGETS, "stop_multipliers": STOP_MULTIPLIERS,
                     "random_walk_hit_rate_no_costs": {str(t): round(1 / (1 + t), 4) for t in TARGETS},
                     "variants": {}}
    for variant in s4.S4_VARIANTS:
        per_segment = []
        for symbol, (hourly, daily, funding, begin) in data.items():
            strategy = variant.build(s4.DailyRegime(daily), s4.Counts())
            signals = collect(hourly, strategy, begin, HOLDOUT_START_MS)
            per_segment.append((hourly, funding, signals, begin))
        grid: dict[str, dict] = {}
        best = None
        for mult in STOP_MULTIPLIERS:
            for target in TARGETS:
                pooled: list = []
                for hourly, funding, signals, begin in per_segment:
                    result = run_backtest(hourly, replay(signals, target, mult), H, costs=BASE_COSTS, funding=funding,
                                          start_ms=begin, end_ms=HOLDOUT_START_MS, gap_entry_as_loss=True)
                    pooled += result.trades
                cell = summarize(pooled)
                grid[f"stop_x{mult:g}/target_{target:g}R"] = cell
                if cell["n"] and cell["hit_rate"] >= GOAL and (best is None or cell["mean_r"] > best[2]["mean_r"]):
                    best = (mult, target, cell)
        payload["variants"][variant.variant_id] = {"hypothesis": variant.hypothesis, "grid": grid,
                                                   "best_cell_at_95": None if best is None else
                                                   {"stop_mult": best[0], "target_r": best[1], **best[2]}}
        line = f"{variant.variant_id:16s}"
        for mult in STOP_MULTIPLIERS:
            cells = [grid[f"stop_x{mult:g}/target_{t:g}R"] for t in TARGETS]
            line += f" | x{mult:g}: " + " ".join(f"{c.get('hit_rate', 0):.0%}/{c.get('mean_r', 0):+.2f}" for c in cells)
        print(line)
        if best is not None:
            print(f"    95 % reached: stop x{best[0]:g}, target {best[1]:g} R, hit {best[2]['hit_rate']:.1%}, "
                  f"E[R] {best[2]['mean_r']:+.3f}, n {best[2]['n']}")
        else:
            print("    95 % not reached in the grid")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"s4_hitrate95_{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"written {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    args = parser.parse_args(argv)
    return explore(ArchiveStore(args.root), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
