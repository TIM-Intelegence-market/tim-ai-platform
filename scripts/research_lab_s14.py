"""Study S14: outcome-blind feasibility count of pairs trading ETH/BTC, SOL/BTC, SOL/ETH (1h from 5m).

    python scripts/research_lab_s14.py count --out DIR    # entry signals per variant, no exits, no R
    python scripts/research_lab_s14.py run --out DIR      # training and validation with R (section 5)

Uses the 5m USD-M klines already fetched for S10 (`scripts/research_lab_s10.py fetch`, run on the
Mac). Holdout months (2025+) are refused by the store and never requested here; S14 is proposed as
its own family and never loads them. Counted are all crossings of |z| = 2 (section 5.1), ignoring
open positions, so the numbers are an upper bound of the trades.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months
from src.research_lab.hypotheses import s14
from src.research_lab.protocol import (
    BASE_COSTS,
    HOLDOUT_START_MS,
    MIN_TRADES_TRAIN,
    STRESS_COSTS,
    UNIVERSE_LIMITATION,
    VALIDATION_START_MS,
)
from src.research_lab.stats.inference import section_trades
from src.research_lab.studies import s14_eval as ev
from src.research_lab.studies import s14_random as sr
from src.research_lab.studies.s13_random import pool_size, pvalue_from_pools

LAST = (2024, 12)
SYMBOLS = {"BTCUSDT": (2020, 1), "ETHUSDT": (2020, 1), "SOLUSDT": (2020, 9)}  # first full USD-M month (as S7/S10)
PAIRS = (("ETHUSDT", "BTCUSDT"), ("SOLUSDT", "BTCUSDT"), ("SOLUSDT", "ETHUSDT"))  # (y, x)
GATE_TRAIN = MIN_TRADES_TRAIN["short"]  # 500
GATE_VALIDATION = MIN_TRADES_TRAIN["short"] // 2  # 250
GATE_DAYS = {"train": 160, "validation": 183}
SECTIONS = {"train": (0, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}
YEARS = range(2020, 2025)
EVALUATED = ("S14-W168", "S14-W720")  # passed the count gate 5.1 on 01.11.2026; both K variants did not


def refs(symbol: str) -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, "5m", symbol) for y, m in months(SYMBOLS[symbol], LAST)]


def funding_refs(symbol: str) -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.FUNDING, y, m, None, symbol) for y, m in months(SYMBOLS[symbol], LAST)]


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def count_pairs(hours: dict[str, list], end_ms: int = HOLDOUT_START_MS) -> tuple[dict, dict]:
    """Entry signals per variant (pooled over pairs) and per pair. ``hours``: 1h bars per symbol."""
    rows: dict[str, list[tuple[str, int, int]]] = {v.variant_id: [] for v in s14.S14_VARIANTS}  # (pair, time, side)
    funnel: dict[str, dict[str, dict[str, int]]] = {v.variant_id: {} for v in s14.S14_VARIANTS}
    for y, x in PAIRS:
        pair = s14.align(y, [b for b in hours[y] if b.open_time < end_ms], x, [b for b in hours[x] if b.open_time < end_ms])
        for variant in s14.S14_VARIANTS:
            found = s14.entries(s14.Signals(pair, variant), pair.times[0] if pair.times else 0, end_ms)
            rows[variant.variant_id] += [(pair.name, pair.times[e.index], e.side) for e in found]
            funnel[variant.variant_id][pair.name] = {"hours": len(pair.times), "signals": len(found)}
            print(f"{pair.name} {variant.variant_id}: {len(pair.times)} hours, {len(found)} signals", flush=True)
    out: dict = {}
    for variant in s14.S14_VARIANTS:
        vid = variant.variant_id
        row: dict = {"params": variant.params, "funnel": funnel[vid]}
        for name, (lo, hi) in SECTIONS.items():
            part = [r for r in rows[vid] if lo <= r[1] < hi]
            row[name] = {"signals": len(part), "signal_days": len({day_of(t) for _, t, _ in part}),
                         "by_pair": {p: sum(1 for q, _, _ in part if q == p) for p in funnel[vid]},
                         "long": sum(1 for _, _, s in part if s > 0), "short": sum(1 for _, _, s in part if s < 0)}
        row["by_year"] = {str(yr): sum(1 for _, t, _ in rows[vid] if day_of(t).startswith(str(yr))) for yr in YEARS}
        row["passes_gate"] = (row["train"]["signals"] >= GATE_TRAIN and row["validation"]["signals"] >= GATE_VALIDATION
                              and row["train"]["signal_days"] >= GATE_DAYS["train"]
                              and row["validation"]["signal_days"] >= GATE_DAYS["validation"])
        out[vid] = row
    return out, funnel


def count(store: ArchiveStore, out_dir: Path) -> int:
    all_refs = [r for symbol in SYMBOLS for r in refs(symbol)]
    payload: dict = {"study": "S14", "commit": _commit(), "outcome_blind": True, "upper_bound": True,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(all_refs),
                     "gate": {"train": GATE_TRAIN, "validation": GATE_VALIDATION, "days": GATE_DAYS},
                     "symbols": {}}
    hours: dict[str, list] = {}
    for symbol, first in SYMBOLS.items():
        bars = store.load_klines(refs(symbol))
        hours[symbol] = s14.hourly(bars)
        payload["symbols"][symbol] = {"first_month": f"{first[0]}-{first[1]:02d}", "bars_5m": len(bars),
                                      "hours": len(hours[symbol])}
        del bars
    payload["variants"], _ = count_pairs(hours)
    for vid, row in payload["variants"].items():
        print(f"{vid}: train {row['train']['signals']} ({row['train']['signal_days']} days), validation "
              f"{row['validation']['signals']} ({row['validation']['signal_days']} days) "
              f"{'PASS' if row['passes_gate'] else 'below gate'}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s14_count_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s14_count_{stamp}.md").write_text(count_markdown(payload))
    print(f"written {path}")
    return 0


def count_markdown(p: dict) -> str:
    g = p["gate"]
    lines = ["# S14 Zähllauf (Machbarkeits-Gate, ergebnisblind)", "",
             (f"Commit `{p['commit']}`, Datensatz-Hash `{p['dataset_hash']}`, erstellt {p['created']}. USD-M 5m zu 1h, "
              f"{', '.join(f'{s} ab {v['first_month']}' for s, v in p['symbols'].items())}, bis 2024-12. Gezählt wird jedes "
              f"Kreuzen von |z| = 2 (offene Positionen ignoriert, also eine Obergrenze der Trades). Gate je Variante, "
              f"gepoolt über die drei Paare: Training ≥ {g['train']} und ≥ {g['days']['train']} Signaltage, Validierung "
              f"≥ {g['validation']} und ≥ {g['days']['validation']} Signaltage. Keine Ausstiege, kein R."), "",
             "| Variante | Training Signale (Tage, long/short) | Validierung Signale (Tage, long/short) | Gate |",
             "|---|---:|---:|---|"]
    for vid, v in p["variants"].items():
        t, val = v["train"], v["validation"]
        lines.append(f"| {vid} | {t['signals']} ({t['signal_days']}, {t['long']}/{t['short']}) | "
                     f"{val['signals']} ({val['signal_days']}, {val['long']}/{val['short']}) | "
                     f"{'BESTANDEN' if v['passes_gate'] else 'nicht bestanden'} |")
    lines += ["", "## Je Paar (2020 bis 2024)", "",
              "| Variante | Paar | Stunden | Signale | davon Training | davon Validierung |", "|---|---|---:|---:|---:|---:|"]
    for vid, v in p["variants"].items():
        for pair, c in v["funnel"].items():
            lines.append(f"| {vid} | {pair} | {c['hours']} | {c['signals']} | {v['train']['by_pair'][pair]} | "
                         f"{v['validation']['by_pair'][pair]} |")
    lines += ["", "Je Kalenderjahr (Signale, gepoolt): " + "; ".join(
        f"{vid} " + ", ".join(f"{y} {n}" for y, n in v["by_year"].items()) for vid, v in p["variants"].items()) + ".",
        "", f"Holdout 2025+ nicht geladen. {UNIVERSE_LIMITATION}"]
    return "\n".join(lines) + "\n"


def run(store: ArchiveStore, out_dir: Path, runs: int = sr.RUNS) -> int:
    """Section 5 for the variants that passed the count gate. Pools for the random comparison are
    built per pair in sorted order with one generator per variant and section, which equals
    ``s14_random.random_pvalue``."""
    all_refs = [r for symbol in SYMBOLS for r in refs(symbol) + funding_refs(symbol)]
    variants = [v for v in s14.S14_VARIANTS if v.variant_id in EVALUATED]
    vids = [v.variant_id for v in variants]
    hours: dict[str, list] = {}
    funding: dict[str, list] = {}
    info: dict = {}
    for symbol, first in SYMBOLS.items():
        bars = store.load_klines(refs(symbol))
        hours[symbol] = [b for b in s14.hourly(bars) if b.open_time < HOLDOUT_START_MS]
        funding[symbol] = [f for f in store.load_funding(funding_refs(symbol)) if f.time < HOLDOUT_START_MS]
        info[symbol] = {"first_month": f"{first[0]}-{first[1]:02d}", "bars_5m": len(bars), "hours": len(hours[symbol]),
                        "funding_rates": len(funding[symbol])}
        del bars
    rngs = {(v, sec): random.Random(sr.SEED) for v in vids for sec in SECTIONS}
    pools: dict = {key: {} for key in rngs}
    trades: dict = {v: {sec: {} for sec in SECTIONS} for v in vids}
    stress: dict = {v: {sec: {} for sec in SECTIONS} for v in vids}
    every: dict = {v: {} for v in vids}
    for y, x in sorted(PAIRS, key=lambda p: f"{p[0][:-4]}/{p[1][:-4]}"):
        pair = s14.align(y, hours[y], x, hours[x])
        for variant in variants:
            vid = variant.variant_id
            kw = {"y_funding": funding[y], "x_funding": funding[x]}
            base = s14.run_pair(pair, variant, pair.times[0], HOLDOUT_START_MS, BASE_COSTS, **kw)
            hard = s14.run_pair(pair, variant, pair.times[0], HOLDOUT_START_MS, STRESS_COSTS, **kw)
            every[vid][pair.name] = section_trades(base, None, HOLDOUT_START_MS)
            data = sr.PairData(pair, s14.Signals(pair, variant), funding[y], funding[x])
            for sec, (lo, hi) in SECTIONS.items():
                part = section_trades(base, lo, hi)
                trades[vid][sec][pair.name] = part
                stress[vid][sec][pair.name] = section_trades(hard, lo, hi)
                if part:
                    sim = sr.draw_pool(data, [t.side for t in part], lo, hi, pool_size(len(part), runs),
                                       rngs[(vid, sec)], BASE_COSTS, pair.name)
                    pools[(vid, sec)][pair.name] = [t.r for t in sim]
                print(f"{pair.name} {vid} {sec}: {len(part)} trades", flush=True)
    payload: dict = {"study": "S14", "commit": _commit(), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(all_refs), "runs": runs, "seed": sr.SEED, "symbols": info,
                     "family": "eigene Familie, kein Holdout", "variants": {}}
    walk = ev.walk_forward_rule(every, min(h[0].open_time for h in hours.values() if h), HOLDOUT_START_MS)
    payload["walk_forward"] = walk
    rows: dict = {}
    for vid in vids:
        row: dict = {}
        for sec in SECTIONS:
            fig = ev.section_figures(trades[vid][sec])
            p = random_mean = None
            if ev.needs_pvalue(fig, sec):
                counts = {s: len(ts) for s, ts in trades[vid][sec].items() if ts}
                observed = sum(t.r for ts in trades[vid][sec].values() for t in ts)
                result = pvalue_from_pools(pools[(vid, sec)], counts, observed, runs, rngs[(vid, sec)])
                p, random_mean = result.p, result.random_mean
            hard = ev.section_figures(stress[vid][sec])
            row[sec] = {"figures": fig, "p": p, "random_mean_r": random_mean, "verdict": ev.section_verdict(fig, p, sec),
                        "stress_expectancy_r": hard["expectancy_r"], "stress_n": hard["n"]}
        both = {s: list(trades[vid]["train"].get(s, [])) + list(trades[vid]["validation"].get(s, []))
                for s in trades[vid]["train"]}
        row["year_stability"] = ev.year_rule(both)
        rows[vid] = row
    train_expectancy = {vid: rows[vid]["train"]["figures"]["expectancy_r"] for vid in vids if rows[vid]["train"]["figures"]["n"]}
    for vid in vids:
        row = rows[vid]
        row["neighbours"] = ev.neighbour_rule(vid, train_expectancy)
        row["verdict"] = ev.final_verdict(row["train"]["verdict"], row["validation"]["verdict"], row["year_stability"], walk,
                                          row["neighbours"])
        payload["variants"][vid] = row
        print(f"{vid}: {row['verdict']}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s14_run_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=sorted) + "\n")
    (out_dir / f"s14_run_{stamp}.md").write_text(run_markdown(payload))
    print(f"written {path}")
    return 0


def _f(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "–"
    if x == float("inf"):
        return "∞"
    if x == float("-inf"):
        return "–∞"
    return f"{x:.{digits}f}".replace(".", ",")


def run_markdown(p: dict) -> str:
    lines = ["# S14 Auswertung Training und Validierung (eigene Familie, kein Holdout)", "",
             (f"Commit `{p['commit']}`, Datensatz-Hash `{p['dataset_hash']}`, erstellt {p['created']}. USD-M 5m zu 1h, "
              f"{', '.join(f'{s} ab {v['first_month']}' for s, v in p['symbols'].items())}, bis 2024-12. Paare ETH/BTC, "
              f"SOL/BTC, SOL/ETH gepoolt. Kosten Protokoll 4.4 je Bein mit Funding, Zufallsvergleich {p['runs']} Läufe, "
              f"Seed {p['seed']}. 1 R = 2σ des Spreads (Einstieg bis Stop)."), "",
             "| Variante | Abschnitt | n (n_eff) | E[R] | E[R] Zufall | p | PF | DD | E[R] doppelte Kosten | Urteil |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for vid, v in p["variants"].items():
        for sec, name in (("train", "Training"), ("validation", "Validierung")):
            r, f = v[sec], v[sec]["figures"]
            verdict = "erfüllt" if r["verdict"]["pass"] else "nicht erfüllt: " + ", ".join(r["verdict"]["reasons"])
            lines.append(f"| {vid} | {name} | {f['n']} ({f['n_eff']}) | {_f(f['expectancy_r'])} | {_f(r['random_mean_r'])} | "
                         f"{_f(r['p'])} | {_f(f['profit_factor'], 2)} | {_f(100 * f['max_drawdown_pct'], 1)} % | "
                         f"{_f(r['stress_expectancy_r'])} | {verdict} |")
    w = p["walk_forward"]
    lines += ["", (f"Walk-Forward 24/6 über beide Varianten: verketteter Erwartungswert {_f(w['chained_expectancy_r'])} R "
                   f"({w['windows']} Fenster, gewählt: {', '.join(w['chosen'])}), {'erfüllt' if w['pass'] else 'nicht erfüllt'}."), ""]
    for vid, v in p["variants"].items():
        nb = ", ".join(f"{n} {_f(x)}" for n, x in v["neighbours"]["neighbours"].items())
        lines.append(f"**{vid}: {v['verdict']}.** Jahresstabilität {'erfüllt' if v['year_stability'] else 'nicht erfüllt'}, "
                     f"Nachbarschaft {'erfüllt' if v['neighbours']['pass'] else 'nicht erfüllt'} (Training E[R] {nb}).")
    lines += ["", "## Beschreibend", "",
              "| Variante | Abschnitt | Trefferquote | Ø Gewinn / Ø Verlust R | Stop | Funding R/Trade | Gebühren R/Trade | Ø Stunden | ETH/BTC E[R] (n) | SOL/BTC E[R] (n) | SOL/ETH E[R] (n) | Long / Short E[R] |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for vid, v in p["variants"].items():
        for sec, name in (("train", "Training"), ("validation", "Validierung")):
            f = v[sec]["figures"]
            per = []
            for pair in ("ETH/BTC", "SOL/BTC", "SOL/ETH"):
                d = f["by_symbol"].get(pair, {"n": 0, "expectancy_r": 0.0})
                per.append(f"{_f(d['expectancy_r'])} ({d['n']})")
            lines.append(f"| {vid} | {name} | {_f(100 * f['win_rate'], 1)} % | {_f(f['avg_win_r'])} / {_f(f['avg_loss_r'])} | "
                         f"{_f(100 * f['catastrophe_stop_share'], 1)} % | {_f(f['mean_funding_r'], 4)} | {_f(f['mean_fee_r'], 4)} | "
                         f"{_f(f['mean_bars_held'], 1)} | " + " | ".join(per) + " | "
                         f"{_f(f['by_side']['long']['expectancy_r'])} / {_f(f['by_side']['short']['expectancy_r'])} |")
    lines += ["", "Ausstiegsgründe: " + "; ".join(
        f"{vid} {name} " + ", ".join(f"{k} {n}" for k, n in v[sec]["figures"]["by_reason"].items())
        for vid, v in p["variants"].items() for sec, name in (("train", "Training"), ("validation", "Validierung"))) + ".",
              "", "Je Kalenderjahr (n, E[R]): " + "; ".join(
        f"{vid} " + ", ".join(f"{y} {d['n']}/{_f(d['expectancy_r'])}" for sec in ("train", "validation")
                              for y, d in v[sec]["figures"]["by_year"].items()) for vid, v in p["variants"].items()) + ".",
              "", "Der Stop wird nur auf Stundenschlüssen geprüft (Präregistrierung 4.3), Verluste können über 1 R liegen.",
              "", f"Holdout 2025+ nicht geladen. Ein Kandidat wäre nur über einen eigenen prospektiven Test bestätigt. {UNIVERSE_LIMITATION}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["count", "run"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    parser.add_argument("--runs", type=int, default=sr.RUNS, help="random runs (default 10 000, fewer only for a smoke test)")
    args = parser.parse_args(argv)
    if args.command == "run":
        return run(ArchiveStore(args.root), args.out, args.runs)
    return count(ArchiveStore(args.root), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
