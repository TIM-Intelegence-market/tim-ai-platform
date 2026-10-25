"""Study S6: outcome-blind fill count for the feasibility gate (section 6.1).

    python scripts/research_lab_s6.py count --out DIR

Reads USD-M 1m klines for BTC/ETH/SOL up to 2024-12 (the store refuses holdout months) and
counts entry fills per variant, instrument and section by the frozen rules in
src/research_lab/hypotheses/s6.py: reference, post-only, trade-through margin, `both`,
conservative locks (every trade assumed to reach the time stop). No stop, target or
result is read. Also reports the empirical tick per month, gaps over 5 minutes, fill days
(clusters) and the projection from the weakest calendar year onto the holdout.
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
from src.research_lab.hypotheses import s6  # noqa: E402
from src.research_lab.protocol import HOLDOUT_START_MS, _utc_ms  # noqa: E402

LAST_MONTH = (2024, 12)
SYMBOLS = {"BTCUSDT": ((2020, 1), (2020, 1)), "ETHUSDT": ((2020, 1), (2020, 1)), "SOLUSDT": ((2020, 9), (2020, 10))}
TRAIN_END = _utc_ms(2023, 1, 1)
HOLDOUT_COIN_MONTHS = 3 * 21
HOLDOUT_MONTHS = 21
GATE_FILLS = 320
GATE_FILL_DAYS = 160


def refs(symbol: str) -> list[ArchiveRef]:
    first, _ = SYMBOLS[symbol]
    return [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, "1m", symbol=symbol) for y, m in months(first, LAST_MONTH)]


def all_refs() -> list[ArchiveRef]:
    return [r for symbol in SYMBOLS for r in refs(symbol)]


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _year(ms: int) -> str:
    return str(datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year)


def gaps_over_bridge(bars) -> list[dict]:
    out = []
    for a, b in zip(bars, bars[1:]):
        if b.open_time - a.open_time > s6.GAP_BRIDGE_MS:
            out.append({"after": datetime.fromtimestamp(a.open_time / 1000, tz=timezone.utc).isoformat(timespec="minutes"),
                        "minutes": (b.open_time - a.open_time) // s6.MINUTE_MS - 1})
    return out


def count(store: ArchiveStore, out_dir: Path) -> int:
    payload: dict = {"study": "S6", "protocol": "S6 0.2 (draft)", "commit": _commit(), "outcome_blind": "fills only, no exits",
                     "gate": {"fills": GATE_FILLS, "fill_days": GATE_FILL_DAYS}, "holdout_coin_months": HOLDOUT_COIN_MONTHS,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dataset_hashes": {},
                     "ticks": {}, "gaps_over_5min": {}, "bars": {}, "coin_months_by_year": {}, "variants": {}}
    per_variant: dict[str, dict] = {v.variant_id: {"counts": {}, "fills_by_month": {}, "fill_days": set(), "both": 0}
                                    for v in s6.S6_VARIANTS}
    for symbol, (_, first_counted) in SYMBOLS.items():
        symbol_refs = refs(symbol)
        bars = [b for b in store.load_klines(symbol_refs) if b.open_time < HOLDOUT_START_MS]
        payload["dataset_hashes"][symbol] = store.dataset_hash(symbol_refs)
        payload["bars"][symbol] = len(bars)
        ticks = s6.empirical_ticks(bars)
        payload["ticks"][symbol] = ticks
        payload["gaps_over_5min"][symbol] = gaps_over_bridge(bars)
        reference = s6.compute_reference(bars)
        begin = _utc_ms(first_counted[0], first_counted[1], 1)
        for y, m in months(first_counted, LAST_MONTH):
            payload["coin_months_by_year"][str(y)] = payload["coin_months_by_year"].get(str(y), 0) + 1
        for variant in s6.S6_VARIANTS:
            for section, (lo, hi) in {"train": (begin, TRAIN_END), "validation": (TRAIN_END, HOLDOUT_START_MS)}.items():
                c = s6.count_fills(bars, variant, lo, hi, reference=reference, ticks=ticks)
                row = per_variant[variant.variant_id]
                row["counts"][f"{symbol}/{section}"] = {"fills": c.fills, "both": c.both, "fills_unlocked": c.fills_unlocked,
                                                        "skipped_cross": c.skipped_cross, "no_reference": c.no_reference,
                                                        "by_side": c.fills_by_side}
                row["fill_days"] |= c.fill_days
                row["both"] += c.both
                for k, v in c.fills_by_month.items():
                    row["fills_by_month"][k] = row["fills_by_month"].get(k, 0) + v
            print(f"  {symbol} {variant.variant_id} done", flush=True)
        del bars, reference
    for variant in s6.S6_VARIANTS:
        row = per_variant[variant.variant_id]
        by_year: dict[str, int] = {}
        for month, n in row["fills_by_month"].items():
            by_year[month[:4]] = by_year.get(month[:4], 0) + n
        days_by_year: dict[str, int] = {}
        for day in row["fill_days"]:
            days_by_year[day[:4]] = days_by_year.get(day[:4], 0) + 1
        density = {y: by_year.get(y, 0) / cm for y, cm in payload["coin_months_by_year"].items()}
        months_by_year = {y: min(cm, 12) for y, cm in payload["coin_months_by_year"].items()}  # calendar months with data
        day_density = {y: days_by_year.get(y, 0) / months_by_year[y] for y in months_by_year}
        weakest = min(density, key=density.get)
        weakest_days = min(day_density, key=day_density.get)
        projected = density[weakest] * HOLDOUT_COIN_MONTHS
        projected_days = day_density[weakest_days] * HOLDOUT_MONTHS
        total = sum(row["fills_by_month"].values())
        payload["variants"][variant.variant_id] = {
            "k": variant.k, "target_r": variant.target_r, "counts": row["counts"], "fills_total": total, "both_total": row["both"],
            "fills_by_year": dict(sorted(by_year.items())), "fill_days_by_year": dict(sorted(days_by_year.items())),
            "density_per_coin_month": {y: round(d, 3) for y, d in density.items()}, "weakest_year": weakest,
            "projected_holdout_fills": round(projected, 1),
            "fill_days_per_month": {y: round(d, 2) for y, d in day_density.items()}, "weakest_year_days": weakest_days,
            "projected_holdout_fill_days": round(projected_days, 1),
            "passes_gate": projected >= GATE_FILLS and projected_days >= GATE_FILL_DAYS}
        print(f"{variant.variant_id:10s} fills {total:6d}  weakest {weakest} -> {projected:7.1f}  fill-days weakest {weakest_days} "
              f"-> {projected_days:6.1f}  {'PASS' if payload['variants'][variant.variant_id]['passes_gate'] else 'below gate'}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"s6_count_{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}.json"
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
