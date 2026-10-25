"""Study S6: outcome-blind fill count for the feasibility gate (section 6.1) and latency check (6.2).

    python scripts/research_lab_s6.py count --out DIR
    python scripts/research_lab_s6.py latency --out DIR

Reads USD-M 1m klines for BTC/ETH/SOL up to 2024-12 (the store refuses holdout months) and
counts entry fills per variant, instrument and section by the frozen rules in
src/research_lab/hypotheses/s6.py: reference, post-only, trade-through margin, `both`,
conservative locks (every trade assumed to reach the time stop). No stop, target or
result is read. Also reports the empirical tick per month, gaps over 5 minutes, fill days
(clusters) and the projection from the weakest calendar year onto the holdout.

`latency` draws 10 training fill days per instrument (seed 20261031), downloads the USD-M
aggTrades archives of those days (verified, reduced to the fill minutes, not kept) and checks
every counted fill for early fills, crossed placement and thin volume (section 6.2). It reads
no exit either.
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
from src.research_lab.studies import s6_latency as lat  # noqa: E402
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


FAMILIES = {2.0: "S6-k2-t15", 3.0: "S6-k3-t15"}  # the target does not change the fills; one variant per k


def training_fills(store: ArchiveStore) -> tuple[dict[str, list[tuple[float, s6.Fill]]], dict[str, set[str]], dict[str, str]]:
    """Counted training fills per symbol for both k families, their calendar days and the dataset hashes."""
    fills: dict[str, list[tuple[float, s6.Fill]]] = {}
    days: dict[str, set[str]] = {}
    hashes: dict[str, str] = {}
    variants = {v.variant_id: v for v in s6.S6_VARIANTS}
    for symbol, (_, first_counted) in SYMBOLS.items():
        symbol_refs = [r for r in refs(symbol) if r.start_ms < TRAIN_END]
        bars = [b for b in store.load_klines(symbol_refs) if b.open_time < TRAIN_END]
        hashes[symbol] = store.dataset_hash(symbol_refs)
        ticks = s6.empirical_ticks(bars)
        reference = s6.compute_reference(bars)
        begin = _utc_ms(first_counted[0], first_counted[1], 1)
        fills[symbol] = []
        days[symbol] = set()
        for k, variant_id in FAMILIES.items():
            found, _, _ = s6.list_fills(bars, variants[variant_id], begin, TRAIN_END, reference=reference, ticks=ticks)
            counted = [f for f in found if f.counted]
            fills[symbol].extend((k, f) for f in counted)
            days[symbol] |= {s6.day_key(f.open_time) for f in counted}
        print(f"  {symbol}: {len(fills[symbol])} counted training fills on {len(days[symbol])} days", flush=True)
        del bars, reference
    return fills, days, hashes


def latency(store: ArchiveStore, minute_store: lat.AggTradesMinuteStore, out_dir: Path) -> int:
    fills, days, hashes = training_fills(store)
    drawn = lat.sample_days(days)
    payload: dict = {"study": "S6", "protocol": "S6 0.3 (draft), section 6.2", "commit": _commit(), "outcome_blind": "entry fills only, no exits",
                     "seed": lat.LATENCY_SEED, "days_per_symbol": lat.DAYS_PER_SYMBOL, "placement_ms": lat.PLACEMENT_MS,
                     "nominal_usdt": s6.NOMINAL, "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "kline_dataset_hashes": hashes, "days": drawn, "archives": {}, "checks": [], "summary": {}}
    checks: list[lat.FillCheck] = []
    for symbol, day_list in drawn.items():
        for day in day_list:
            ref = lat.AggTradesDayRef(symbol, datetime.strptime(day, "%Y-%m-%d").date())
            todays = [(k, f) for k, f in fills[symbol] if s6.day_key(f.open_time) == day]
            minutes = {f.open_time for _, f in todays}
            trades, digest = minute_store.load(ref, minutes)
            payload["archives"][f"{symbol}/{day}"] = digest
            for k, f in todays:
                for side, limit, delta in zip(f.sides, f.limits, f.margins):
                    checks.append(lat.check_fill(trades[f.open_time], f.open_time, symbol=symbol, k=k, side=side, limit=limit, delta=delta))
            print(f"  {symbol} {day}: {len(todays)} fills checked", flush=True)
    payload["checks"] = [lat.check_as_dict(c) for c in checks]
    summary = {"pooled": lat.summarize(checks)}
    for k in FAMILIES:
        summary[f"k{int(k)}"] = lat.summarize([c for c in checks if c.k == k])
    for symbol in drawn:
        summary[symbol] = lat.summarize([c for c in checks if c.symbol == symbol])
    payload["summary"] = summary
    for name, row in summary.items():
        print(f"{name:8s} checked {row['checked']:5d}  doubtful {row['doubtful']:4d}  lambda {row['lambda']}  reasons {row['reasons']}"
              f"  {'RAISE DELTA' if row['raise_delta'] else 'ok'}")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"s6_latency_{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"written {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["count", "latency"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    args = parser.parse_args(argv)
    if args.command == "latency":
        return latency(ArchiveStore(args.root), lat.AggTradesMinuteStore(args.root), args.out)
    return count(ArchiveStore(args.root), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
