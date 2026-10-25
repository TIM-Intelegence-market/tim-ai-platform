"""Study S4, exploratory look (NOT confirmatory): hit rate, E[R], profit factor and drawdown
of the 10 frozen S4 variants on training (to 2022-12) and validation (2023-2024).

    python scripts/research_lab_s4_explore.py --out DIR

S4 ended at its feasibility gate (section 6.1) as "not testable". Uzi asked on
2026-10-25 for the hit rate anyway. This run reads only data before 2025 (the store
refuses holdout months). Its numbers are a look at the data, not evidence: they are
not corrected for multiple tests and they mark 2020-2024 as "seen" for any later
design. Rules, costs and exits are exactly those of S4 1.0 (s4.py, gap entries as
losses, target 0.75 R, base and stress costs).
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.backtest.engine import run_backtest  # noqa: E402
from src.research_lab.data.archive import Dataset  # noqa: E402
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore  # noqa: E402
from src.research_lab.hypotheses import s4  # noqa: E402
from src.research_lab.protocol import BASE_COSTS, HOLDOUT_START_MS, STRESS_COSTS  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import research_lab_s4 as base  # noqa: E402

H = 3_600_000


def wilson(hits: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return (centre - half, centre + half)


def summarize(trades: list) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0}
    rs = [t.r for t in sorted(trades, key=lambda t: t.exit_time)]
    hits = sum(1 for t in trades if t.reason in ("target", "target_gap") and t.r > 0)
    gains, losses = sum(r for r in rs if r > 0), -sum(r for r in rs if r < 0)
    equity = peak = drawdown = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    low, high = wilson(hits, n)
    reasons: dict[str, int] = {}
    for t in trades:
        reasons[t.reason] = reasons.get(t.reason, 0) + 1
    return {"n": n, "hit_rate": round(hits / n, 4), "hit_ci95": [round(low, 4), round(high, 4)],
            "mean_r": round(sum(rs) / n, 4), "sum_r": round(sum(rs), 2),
            "profit_factor": round(gains / losses, 3) if losses else None, "max_drawdown_r": round(drawdown, 2),
            "exit_reasons": dict(sorted(reasons.items()))}


def explore(store: ArchiveStore, out_dir: Path) -> int:
    data = {}
    for symbol, (_, start) in base.SYMBOLS.items():
        hourly = [b for b in store.load_klines(base.refs(symbol, Dataset.KLINES, "1h")) if b.open_time < HOLDOUT_START_MS]
        daily = [b for b in store.load_klines(base.refs(symbol, Dataset.KLINES, "1d")) if b.open_time < HOLDOUT_START_MS]
        funding = [f for f in store.load_funding(base.refs(symbol, Dataset.FUNDING, None)) if f.time < HOLDOUT_START_MS]
        data[symbol] = (hourly, daily, funding, base._utc_ms(start[0], start[1], 1))
    sections = {"train": lambda begin: (begin, base.TRAIN_END), "validation": lambda begin: (base.TRAIN_END, HOLDOUT_START_MS)}
    payload: dict = {"study": "S4", "kind": "EXPLORATORY, not confirmatory; holdout untouched", "commit": base._commit(),
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "hit_definition": "target reached and net R > 0", "variants": {}}
    for variant in s4.S4_VARIANTS:
        entry: dict = {"hypothesis": variant.hypothesis}
        for label, costs in (("base", BASE_COSTS), ("stress", STRESS_COSTS)):
            pooled: list = []
            parts: dict = {}
            for symbol, (hourly, daily, funding, begin) in data.items():
                for section, window in sections.items():
                    lo, hi = window(begin)
                    strategy = variant.build(s4.DailyRegime(daily), s4.Counts())
                    result = run_backtest(hourly, strategy, H, costs=costs, funding=funding, start_ms=lo, end_ms=hi,
                                          gap_entry_as_loss=True)
                    parts[f"{symbol}/{section}"] = summarize(result.trades)
                    pooled += result.trades
            entry[label] = {"pooled": summarize(pooled), "parts": parts}
        payload["variants"][variant.variant_id] = entry
        b, st = entry["base"]["pooled"], entry["stress"]["pooled"]
        print(f"{variant.variant_id:16s} n {b['n']:5d}  hit {b.get('hit_rate', 0):.1%}  "
              f"CI [{b['hit_ci95'][0]:.1%}, {b['hit_ci95'][1]:.1%}]  E[R] {b['mean_r']:+.3f}  "
              f"PF {b['profit_factor']}  DD {b['max_drawdown_r']}R  | stress E[R] {st['mean_r']:+.3f}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"s4_explore_{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}.json"
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
