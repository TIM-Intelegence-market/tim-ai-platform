"""Study S5: outcome-blind episode count for the feasibility gate (section 6.1).

    python scripts/research_lab_s5.py count --out DIR

Reads USD-M 1h klines, spot 1h klines and funding for BTC/ETH/SOL up to 2024-12 (the
store refuses holdout months) and counts carry episodes per variant, instrument and
section by the frozen rules in src/research_lab/hypotheses/s5.py. No price enters the
count. The funding-sum check from section 6.1 is NOT run here (it would reveal a
partial result); it is a separate flag for a later, explicitly approved run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.archive import ArchiveRef, Dataset, Market  # noqa: E402
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months  # noqa: E402
from src.research_lab.hypotheses import s5  # noqa: E402
from src.research_lab.protocol import HOLDOUT_START_MS, _utc_ms  # noqa: E402

LAST_MONTH = (2024, 12)
# (perp archive start, spot archive start, first counted month), section 3 of the study.
SYMBOLS = {"BTCUSDT": ((2020, 1), (2020, 1), (2020, 1)), "ETHUSDT": ((2020, 1), (2020, 1), (2020, 1)),
           "SOLUSDT": ((2020, 9), (2020, 8), (2020, 10))}
TRAIN_END = _utc_ms(2023, 1, 1)
HOLDOUT_COIN_MONTHS = 3 * 21
GATE = 120
PLANNING_RHO = 0.5  # intra-cluster correlation assumed for the planning design effect


def refs(symbol: str, market: Market, dataset: Dataset, interval: str | None) -> list[ArchiveRef]:
    perp_start, spot_start, _ = SYMBOLS[symbol]
    first = spot_start if market is Market.SPOT else perp_start
    return [ArchiveRef(market, dataset, y, m, interval, symbol=symbol) for y, m in months(first, LAST_MONTH)]


def all_refs() -> list[ArchiveRef]:
    out: list[ArchiveRef] = []
    for symbol in SYMBOLS:
        out += refs(symbol, Market.USDM, Dataset.KLINES, "1h") + refs(symbol, Market.SPOT, Dataset.KLINES, "1h")
        out += refs(symbol, Market.USDM, Dataset.FUNDING, None)
    return out


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _year_of(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year


def count(store: ArchiveStore, out_dir: Path) -> int:
    payload: dict = {"study": "S5", "protocol": "S5 0.3 (draft)", "commit": _commit(), "gate_episodes": GATE,
                     "holdout_coin_months": HOLDOUT_COIN_MONTHS, "outcome_blind": True, "funding_sum_check": "not run",
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dataset_hashes": {},
                     "coin_months_by_year": {}, "variants": {}}
    data = {}
    for symbol, (_, _, first_counted) in SYMBOLS.items():
        perp_refs, spot_refs = refs(symbol, Market.USDM, Dataset.KLINES, "1h"), refs(symbol, Market.SPOT, Dataset.KLINES, "1h")
        funding_refs = refs(symbol, Market.USDM, Dataset.FUNDING, None)
        perp = [b for b in store.load_klines(perp_refs) if b.open_time < HOLDOUT_START_MS]
        spot = [b for b in store.load_klines(spot_refs) if b.open_time < HOLDOUT_START_MS]
        funding = [f for f in store.load_funding(funding_refs) if f.time < HOLDOUT_START_MS]
        payload["dataset_hashes"][symbol] = store.dataset_hash(perp_refs + spot_refs + funding_refs)
        begin = _utc_ms(first_counted[0], first_counted[1], 1)
        data[symbol] = (s5.common_hours(perp, spot), funding, begin)
        for y, m in months(first_counted, LAST_MONTH):
            payload["coin_months_by_year"][str(y)] = payload["coin_months_by_year"].get(str(y), 0) + 1
    for variant in s5.S5_VARIANTS:
        rows: dict = {}
        all_episodes: list[s5.Episode] = []
        for symbol, (hours, funding, begin) in data.items():
            for section, (lo, hi) in {"train": (begin, TRAIN_END), "validation": (TRAIN_END, HOLDOUT_START_MS)}.items():
                result = s5.episodes(funding, hours, variant, lo, hi)
                durations = sorted(e.duration_ms / s5.DAY_MS for e in result.episodes)
                rows[f"{symbol}/{section}"] = {"episodes": len(result.episodes), "by_reason": result.by_reason,
                                               "invalid_signals": result.invalid_signals,
                                               "skipped_locked": result.skipped_locked,
                                               "median_days": durations[len(durations) // 2] if durations else None}
                all_episodes += result.episodes
        by_year: dict[str, int] = {}
        for episode in all_episodes:
            key = str(_year_of(episode.entry_fill))
            by_year[key] = by_year.get(key, 0) + 1
        density = {y: by_year.get(y, 0) / cm for y, cm in payload["coin_months_by_year"].items()}
        weakest_year = min(density, key=density.get)
        projected = density[weakest_year] * HOLDOUT_COIN_MONTHS
        monthly = s5.monthly_counts(all_episodes)
        mean_cluster = sum(monthly.values()) / len(monthly) if monthly else 0.0
        design_effect = 1 + (mean_cluster - 1) * PLANNING_RHO if mean_cluster > 1 else 1.0
        payload["variants"][variant.variant_id] = {
            "theta_units": variant.theta_units, "hold_days": variant.hold_ms // s5.DAY_MS, "counts": rows,
            "episodes_total": len(all_episodes), "episodes_by_year": dict(sorted(by_year.items())),
            "density_per_coin_month": {y: round(d, 3) for y, d in density.items()}, "weakest_year": weakest_year,
            "projected_holdout": round(projected, 1), "passes_gate": projected >= GATE,
            "mean_episodes_per_month_cluster": round(mean_cluster, 2),
            "planning_design_effect_rho_0_5": round(design_effect, 2),
            "projected_effective": round(projected / design_effect, 1)}
        print(f"{variant.variant_id:12s} episodes {len(all_episodes):5d}  weakest {weakest_year} "
              f"projected {projected:6.1f}  D~{design_effect:.2f}  effective {projected / design_effect:6.1f}  "
              f"{'PASS' if projected >= GATE else 'below gate'}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"s5_count_{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"written {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["count"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    args = parser.parse_args(argv)
    return count(ArchiveStore(args.root), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
