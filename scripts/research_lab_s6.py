"""Study S6: outcome-blind fill count for the feasibility gate (section 6.1) and latency check (6.2).

    python scripts/research_lab_s6.py count --out DIR
    python scripts/research_lab_s6.py latency --out DIR
    python scripts/research_lab_s6.py train --latency reports/s6_latency_<stamp>.json --out DIR
    python scripts/research_lab_s6.py register-status reports/s6_train_<stamp>.json

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

`train` runs training (to 2022-12) and validation (2023-24) for all six registered variants
with S6 costs, stress costs (fill haircut lambda from the latency report) and the protocol cost
model (re-priced, reported only), baselines A/B/C, year stability, walk-forward over all
variants and the neighbourhood rule, and writes the candidate list (section 5.1, at most
two). It never loads 2025+. `register-status` writes the resulting statuses into the register.
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
from src.research_lab.stats.register import HypothesisRegister  # noqa: E402
from src.research_lab.studies import s6_eval as ev  # noqa: E402
from src.research_lab.studies import s6_latency as lat  # noqa: E402
from src.research_lab.protocol import HOLDOUT_START_MS, UNIVERSE_LIMITATION, _utc_ms  # noqa: E402

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


def funding_refs(symbol: str) -> list[ArchiveRef]:
    first, _ = SYMBOLS[symbol]
    return [ArchiveRef(Market.USDM, Dataset.FUNDING, y, m, None, symbol=symbol) for y, m in months(first, LAST_MONTH)]


SECTIONS = {"train": (None, TRAIN_END), "validation": (TRAIN_END, HOLDOUT_START_MS)}


def _summary_dict(s: ev.Summary) -> dict:
    d = {k: getattr(s, k) for k in ev.Summary.__dataclass_fields__}
    d["profit_factor"] = None if d["profit_factor"] == float("inf") else d["profit_factor"]
    return d


def _trade_dict(t: s6.Trade) -> dict:
    return {"side": t.side, "entry_time": t.entry_time, "entry_fill": t.entry_fill, "exit_time": t.exit_time, "exit_fill": t.exit_fill,
            "reason": t.reason, "ambiguous": t.ambiguous, "fees": round(t.fees, 6), "funding": round(t.funding, 6), "net_r": round(t.net_r, 6),
            "bars_held": t.bars_held}


def train(store: ArchiveStore, latency_report: Path, out_dir: Path) -> int:
    latency = json.loads(latency_report.read_text())
    lam = latency["summary"]["pooled"]["lambda"]
    if lam is None:
        raise SystemExit("latency report has no lambda")
    if latency["summary"]["pooled"]["raise_delta"]:
        raise SystemExit("latency check demands a higher delta before any training run (section 6.2)")
    payload: dict = {"study": "S6", "protocol": "S6 1.0, sections 5.1, 5.4, 7", "commit": _commit(), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "latency_report": latency_report.name, "lambda": lam, "holdout": "not loaded", "universe_limitation": UNIVERSE_LIMITATION, "dataset_hashes": {}, "funding_hashes": {},
                     "variants": {}, "walk_forward": {}, "candidates": [], "register_status": {}}
    by_id = {v.variant_id: v for v in s6.S6_VARIANTS}
    trades: dict[str, dict[str, dict[str, list[s6.Trade]]]] = {vid: {sec: {} for sec in SECTIONS} for vid in by_id}  # vid/section/symbol
    stress: dict[str, dict[str, dict[str, list[s6.Trade]]]] = {vid: {sec: {} for sec in SECTIONS} for vid in by_id}
    gap_alt: dict[str, dict[str, dict[str, list[s6.Trade]]]] = {vid: {sec: {} for sec in SECTIONS} for vid in by_id}
    deciles: dict[str, dict[str, dict[str, list[tuple[str, int]]]]] = {vid: {sec: {} for sec in SECTIONS} for vid in by_id}
    pools: dict[str, dict[str, dict[str, ev.Pool]]] = {vid: {sec: {} for sec in SECTIONS} for vid in by_id}
    pools_protocol: dict[str, dict[str, dict[str, ev.Pool]]] = {vid: {sec: {} for sec in SECTIONS} for vid in by_id}
    mirrored: dict[str, dict[str, dict[str, list[s6.Trade]]]] = {vid: {sec: {} for sec in SECTIONS} for vid in by_id}
    counts: dict[str, dict[str, dict]] = {vid: {} for vid in by_id}
    for symbol, (_, first_counted) in SYMBOLS.items():
        symbol_refs = refs(symbol)
        bars = [b for b in store.load_klines(symbol_refs) if b.open_time < HOLDOUT_START_MS]
        f_refs = funding_refs(symbol)
        funding = [f for f in store.load_funding(f_refs) if f.time < HOLDOUT_START_MS]
        payload["dataset_hashes"][symbol] = store.dataset_hash(symbol_refs)
        payload["funding_hashes"][symbol] = store.dataset_hash(f_refs)
        ticks = s6.empirical_ticks(bars)
        reference = s6.compute_reference(bars)
        begin = _utc_ms(first_counted[0], first_counted[1], 1)
        cuts = {sec: ev.sigma_deciles(reference, bars, lo or begin, hi) for sec, (lo, hi) in SECTIONS.items()}
        for vid, variant in by_id.items():
            for sec, (lo, hi) in SECTIONS.items():
                lo = lo or begin
                sim = s6.simulate(bars, funding, variant, lo, hi, s6.BASE_COSTS, reference=reference, ticks=ticks)
                sim_stress = s6.simulate(bars, funding, variant, lo, hi, s6.STRESS_COSTS, reference=reference, ticks=ticks)
                trades[vid][sec][symbol] = sim.trades
                stress[vid][sec][symbol] = sim_stress.trades
                gap_alt[vid][sec][symbol] = ev.gap_alternative(sim.trades, bars, s6.BASE_COSTS)
                deciles[vid][sec][symbol] = [(symbol, ev.decile_of(reference.sigma30[t.entry_index], cuts[sec])) for t in sim.trades]
                pools[vid][sec][symbol] = ev.build_pool(bars, reference, funding, variant, lo, hi, s6.BASE_COSTS, ticks, cuts=cuts[sec])
                pools_protocol[vid][sec][symbol] = ev.build_pool(bars, reference, funding, variant, lo, hi, ev.PROTOCOL_COSTS, ticks,
                                                                 cuts=cuts[sec], per_decile=ev.POOL_PER_DECILE // 4)
                mirrored[vid][sec][symbol] = ev.mirrored_trades(bars, sim.trades, variant, s6.BASE_COSTS, hi, ticks, funding)
                counts[vid][f"{symbol}/{sec}"] = {"trades": len(sim.trades), "skipped_cross": sim.skipped_cross, "no_reference": sim.no_reference,
                                                  "by_reason": sim.by_reason, "stress_trades": len(sim_stress.trades)}
                print(f"  {symbol} {vid} {sec}: {len(sim.trades)} trades", flush=True)
        del bars, reference, funding
    train_expectancy: dict[str, float] = {}
    validation_expectancy: dict[str, float] = {}
    passed_training: list[str] = []
    for vid, variant in by_id.items():
        row: dict = {"k": variant.k, "target_r": variant.target_r, "counts": counts[vid], "sections": {}}
        for sec in SECTIONS:
            pooled = [t for ts in trades[vid][sec].values() for t in ts]
            summary = ev.summarize(pooled)
            fill_deciles = [d for ds in deciles[vid][sec].values() for d in ds]
            p_a, mean_a = ev.baseline_a_pvalue(fill_deciles, pools[vid][sec], summary.expectancy)
            all_pool = [r for pool in pools[vid][sec].values() for rs in pool.results.values() for r in rs]
            all_pool_protocol = [r for pool in pools_protocol[vid][sec].values() for rs in pool.results.values() for r in rs]
            stressed = ev.fill_haircut([t for ts in stress[vid][sec].values() for t in ts], lam)
            protocol_trades = [ev.reprice(t, s6.BASE_COSTS, ev.PROTOCOL_COSTS) for t in pooled]
            lo_b, hi_b = ev.day_block_bootstrap(pooled)
            sec_row = {
                "summary": _summary_dict(summary),
                "baseline_a": {"p": p_a, "mean_expectancy": mean_a, "hit_rate_pool": (sum(1 for r in all_pool if r > 0) / len(all_pool)) if all_pool else None},
                "baseline_b_mirrored": _summary_dict(ev.summarize([t for ts in mirrored[vid][sec].values() for t in ts])),
                "baseline_c_unmatched": {"expectancy": (sum(all_pool) / len(all_pool)) if all_pool else None,
                                         "expectancy_protocol_costs": (sum(all_pool_protocol) / len(all_pool_protocol)) if all_pool_protocol else None},
                "stress_after_haircut": _summary_dict(ev.summarize(stressed)),
                "protocol_costs": _summary_dict(ev.summarize(protocol_trades)),
                "gap_after": _summary_dict(ev.summarize([t for ts in gap_alt[vid][sec].values() for t in ts])),
                "bootstrap_90": [lo_b, hi_b],
                "by_symbol": {sym: _summary_dict(ev.summarize(ts)) for sym, ts in trades[vid][sec].items()},
                "by_side": {name: _summary_dict(ev.summarize([t for t in pooled if t.side == side])) for name, side in (("long", s6.LONG), ("short", s6.SHORT))},
                "bars_held_median": sorted(t.bars_held for t in pooled)[len(pooled) // 2] if pooled else None,
                "year_stability": ev.year_stability(pooled),
            }
            row["sections"][sec] = sec_row
            if sec == "train":
                train_expectancy[vid] = summary.expectancy
                row["training"] = ev.training_verdict(summary, p_a)
            else:
                validation_expectancy[vid] = summary.expectancy
                row["_validation_summary"] = summary
                row["_validation_p"] = p_a
        payload["variants"][vid] = row
        if row["training"]["pass"]:
            passed_training.append(vid)
    begin_all = min(_utc_ms(fc[0], fc[1], 1) for _, fc in SYMBOLS.values())
    both_sections = {vid: [t for sec in SECTIONS for ts in trades[vid][sec].values() for t in ts] for vid in by_id}
    payload["walk_forward"] = ev.walk_forward(both_sections, begin_all, HOLDOUT_START_MS)
    passed_validation: list[str] = []
    for vid, variant in by_id.items():
        row = payload["variants"][vid]
        robustness = {"year_stability": ev.year_stability(both_sections[vid])["pass"], "walk_forward": payload["walk_forward"]["pass"],
                      "neighbours": ev.neighbours_positive(variant, train_expectancy)["pass"]}
        row["robustness"] = {"year_stability_all": ev.year_stability(both_sections[vid]), "neighbours": ev.neighbours_positive(variant, train_expectancy)}
        if row["training"]["pass"]:
            row["validation"] = ev.validation_verdict(row.pop("_validation_summary"), row.pop("_validation_p"), robustness)
            if row["validation"]["pass"]:
                passed_validation.append(vid)
        else:
            row.pop("_validation_summary"), row.pop("_validation_p")
            row["validation"] = {"pass": False, "reasons": ["not run: training failed"]}
    candidates = ev.select_candidates(validation_expectancy, passed_validation)
    payload["candidates"] = candidates
    for vid in by_id:
        row = payload["variants"][vid]
        if not row["training"]["pass"]:
            status, note = "failed_train", "Training: " + "; ".join(row["training"]["reasons"])
        elif not row["validation"]["pass"]:
            status, note = "failed_validation", "Validierung: " + "; ".join(row["validation"]["reasons"])
        elif vid in candidates:
            status, note = "candidate", f"Kandidatin nach 5.1 Schritt 3, E[R] Validierung {validation_expectancy[vid]:.4f} R"
        else:
            status, note = "not_selected", "bestanden, aber nicht unter den zwei Kandidatinnen (eine je Ziel)"
        payload["register_status"][vid] = {"status": status, "note": note}
        print(f"{vid:10s} train E {train_expectancy[vid]:+.4f} hit {row['sections']['train']['summary']['hit_rate']:.3f} "
              f"p {row['sections']['train']['baseline_a']['p']:.4f} | val E {validation_expectancy[vid]:+.4f} "
              f"hit {row['sections']['validation']['summary']['hit_rate']:.3f} -> {status}")
    print(f"walk-forward: {payload['walk_forward']}")
    print(f"candidates: {candidates}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s6_train_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    trades_path = out_dir / f"s6_train_{stamp}_trades.json"
    trades_path.write_text(json.dumps({vid: {sec: {sym: [_trade_dict(t) for t in ts] for sym, ts in secs.items()} for sec, secs in v.items()}
                                       for vid, v in trades.items()}, ensure_ascii=False) + "\n")
    print(f"written {path} and {trades_path}")
    return 0


def register_status(report: Path, register_path: Path) -> int:
    payload = json.loads(report.read_text())
    register = HypothesisRegister(register_path)
    for vid, row in payload["register_status"].items():
        register.set_status(vid, row["status"], f"{row['note']} ({report.name}, Commit {payload['commit'][:7]})")
        print(f"{vid}: {row['status']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["count", "latency", "train", "register-status"])
    parser.add_argument("report", nargs="?", type=Path, help="train report for register-status")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    parser.add_argument("--latency", type=Path, help="latency report (required for train)")
    parser.add_argument("--register", type=Path, default=Path("docs/research_lab/REGISTER.jsonl"))
    args = parser.parse_args(argv)
    if args.command == "latency":
        return latency(ArchiveStore(args.root), lat.AggTradesMinuteStore(args.root), args.out)
    if args.command == "train":
        if args.latency is None:
            parser.error("train needs --latency <report> (section 6.2 runs before any result)")
        return train(ArchiveStore(args.root), args.latency, args.out)
    if args.command == "register-status":
        if args.report is None:
            parser.error("register-status needs the train report")
        return register_status(args.report, args.register)
    return count(ArchiveStore(args.root), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
