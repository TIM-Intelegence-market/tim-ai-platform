"""Study S13: outcome-blind feasibility count of the noise-band breakout (BTC/ETH/SOL, 1m).

    python scripts/research_lab_s13.py count --out DIR    # first signal per session, no exits, no R
    python scripts/research_lab_s13.py run --out DIR      # training and validation with R (section 5)

Uses the 1m USD-M klines and funding already fetched for S10 (`scripts/research_lab_s10.py fetch`,
run on the Mac). Holdout months (2025+) are refused by the store and never requested here; S13 is
its own family and never loads them (protocol entry 01.11.2026). One instrument at a time is held
in memory (about 2.6 million 1m bars).
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

from src.research_lab.backtest.engine import run_backtest
from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months
from src.research_lab.hypotheses import s13
from src.research_lab.protocol import (
    BASE_COSTS,
    HOLDOUT_START_MS,
    MIN_TRADES_TRAIN,
    STRESS_COSTS,
    UNIVERSE_LIMITATION,
    VALIDATION_START_MS,
    _utc_ms,
)
from src.research_lab.stats.inference import section_trades
from src.research_lab.studies import s13_eval as ev
from src.research_lab.studies import s13_random as sr

LAST = (2024, 12)
SYMBOLS = {"BTCUSDT": (2020, 1), "ETHUSDT": (2020, 1), "SOLUSDT": (2020, 9)}  # first full USD-M month (as S7/S10)
GATE_TRAIN = MIN_TRADES_TRAIN["short"]  # 500
GATE_VALIDATION = MIN_TRADES_TRAIN["short"] // 2  # 250
GATE_DAYS = {"train": 160, "validation": 183}  # distinct signal days (protocol 1.3 A3 numbers)
YEARS = range(2020, 2025)


def refs(symbol: str) -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, "1m", symbol) for y, m in months(SYMBOLS[symbol], LAST)]


def funding_refs(symbol: str) -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.FUNDING, y, m, None, symbol) for y, m in months(SYMBOLS[symbol], LAST)]


SECTIONS = {"train": (0, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def count(store: ArchiveStore, out_dir: Path) -> int:
    all_refs = [r for symbol in SYMBOLS for r in refs(symbol)]
    payload: dict = {"study": "S13", "commit": _commit(), "outcome_blind": True,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(all_refs),
                     "gate": {"train": GATE_TRAIN, "validation": GATE_VALIDATION, "days": GATE_DAYS},
                     "symbols": {}, "variants": {}}
    rows: dict[str, list[tuple[str, s13.FirstSignal]]] = {v.variant_id: [] for v in s13.S13_VARIANTS}
    funnels: dict[str, dict[str, dict[str, int]]] = {v.variant_id: {} for v in s13.S13_VARIANTS}
    for symbol, first in SYMBOLS.items():
        start = _utc_ms(*first, 1)
        bars = store.load_klines(refs(symbol))
        payload["symbols"][symbol] = {"first_month": f"{first[0]}-{first[1]:02d}", "bars_1m": len(bars)}
        for variant in s13.S13_VARIANTS:
            table = s13.build_table(bars, variant, start, HOLDOUT_START_MS)
            result = s13.count_signals(bars, table, start)
            rows[variant.variant_id] += [(symbol, sig) for sig in result.signals]
            funnels[variant.variant_id][symbol] = {k: getattr(result.counts, k) for k in result.counts.__dataclass_fields__}
            print(f"{symbol} {variant.variant_id}: {result.counts}", flush=True)
        del bars
    for variant in s13.S13_VARIANTS:
        part_rows = rows[variant.variant_id]
        row: dict = {"params": variant.params, "funnel": funnels[variant.variant_id]}
        for name, (lo, hi) in {"train": (0, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}.items():
            part = [(s, x) for s, x in part_rows if lo <= x.signal_time < hi]
            row[name] = {"signals": len(part), "signal_days": len({x.day for _, x in part}),
                         "btc": sum(1 for s, _ in part if s == "BTCUSDT"),
                         "long": sum(1 for _, x in part if x.direction > 0), "short": sum(1 for _, x in part if x.direction < 0)}
        row["by_year"] = {str(y): sum(1 for _, x in part_rows if x.day.year == y) for y in YEARS}
        row["passes_gate"] = (row["train"]["signals"] >= GATE_TRAIN and row["validation"]["signals"] >= GATE_VALIDATION
                              and row["train"]["signal_days"] >= GATE_DAYS["train"]
                              and row["validation"]["signal_days"] >= GATE_DAYS["validation"])
        payload["variants"][variant.variant_id] = row
        print(f"{variant.variant_id}: train {row['train']['signals']} ({row['train']['signal_days']} days), validation "
              f"{row['validation']['signals']} ({row['validation']['signal_days']} days) "
              f"{'PASS' if row['passes_gate'] else 'below gate'}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s13_count_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s13_count_{stamp}.md").write_text(count_markdown(payload))
    print(f"written {path}")
    return 0


FUNNEL = (("sessions", "Sitzungen"), ("warmup", "Vorlauf (14)"), ("no_band", "kein Band (Daten)"),
          ("no_breakout", "kein Ausbruch"), ("signals", "Signale"))


def count_markdown(p: dict) -> str:
    g = p["gate"]
    lines = ["# S13 Zähllauf (Machbarkeits-Gate, ergebnisblind)", "",
             (f"Commit `{p['commit']}`, Datensatz-Hash `{p['dataset_hash']}`, erstellt {p['created']}. USD-M 1m, "
             f"{', '.join(f'{s} ab {v['first_month']}' for s, v in p['symbols'].items())}, bis 2024-12. Gezählt wird das "
             f"erste Signal je Sitzung. Gate je Variante, gepoolt: Training ≥ {g['train']} und ≥ {g['days']['train']} "
             f"Signaltage, Validierung ≥ {g['validation']} und ≥ {g['days']['validation']} Signaltage. Keine Ausstiege, kein R."), "",
             "| Variante | Training Signale (Tage, BTC, long/short) | Validierung Signale (Tage, BTC, long/short) | Gate |",
             "|---|---:|---:|---|"]
    for vid, v in p["variants"].items():
        t, val = v["train"], v["validation"]
        lines.append(f"| {vid} | {t['signals']} ({t['signal_days']}, {t['btc']}, {t['long']}/{t['short']}) | "
                     f"{val['signals']} ({val['signal_days']}, {val['btc']}, {val['long']}/{val['short']}) | "
                     f"{'BESTANDEN' if v['passes_gate'] else 'nicht bestanden'} |")
    lines += ["", "## Trichter je Instrument (2020 bis 2024)", "",
              "| Variante | Instrument | " + " | ".join(label for _, label in FUNNEL) + " |",
              "|---|---|" + "---:|" * len(FUNNEL)]
    for vid, v in p["variants"].items():
        for symbol, c in v["funnel"].items():
            lines.append(f"| {vid} | {symbol} | " + " | ".join(str(c[k]) for k, _ in FUNNEL) + " |")
    lines += ["", "Je Kalenderjahr (Signale, gepoolt): " + "; ".join(
        f"{vid} " + ", ".join(f"{y} {n}" for y, n in v["by_year"].items()) for vid, v in p["variants"].items()) + ".",
        "", f"Holdout 2025+ nicht geladen. {UNIVERSE_LIMITATION}"]
    return "\n".join(lines) + "\n"


def session_end_exits(table: s13.NoiseTable) -> set[int]:
    """Exit moments of the session end: the open of the bar after each last check bar."""
    return {t + s13.INTERVAL_MS for t, check in table.checks.items() if check.last}


def run(store: ArchiveStore, out_dir: Path, runs: int = sr.RUNS) -> int:
    """Section 5 for both variants. Pools for the random comparison are built per instrument in sorted
    order with one generator per variant and section, which equals ``s13_random.random_pvalue``."""
    symbols = sorted(SYMBOLS)
    all_refs = [r for symbol in symbols for r in refs(symbol) + funding_refs(symbol)]
    variants = [v.variant_id for v in s13.S13_VARIANTS]
    rngs = {(v, sec): random.Random(sr.SEED) for v in variants for sec in SECTIONS}
    pools: dict = {key: {} for key in rngs}
    trades: dict = {v: {sec: {} for sec in SECTIONS} for v in variants}
    stress: dict = {v: {sec: {} for sec in SECTIONS} for v in variants}
    every: dict = {v: {} for v in variants}  # all trades up to the holdout, for the walk-forward
    ends: dict = {v: {} for v in variants}
    info: dict = {}
    for symbol in symbols:
        start = _utc_ms(*SYMBOLS[symbol], 1)
        bars = [b for b in store.load_klines(refs(symbol)) if b.open_time < HOLDOUT_START_MS]
        funding = [f for f in store.load_funding(funding_refs(symbol)) if f.time < HOLDOUT_START_MS]
        info[symbol] = {"first_month": f"{SYMBOLS[symbol][0]}-{SYMBOLS[symbol][1]:02d}", "bars_1m": len(bars),
                        "funding_rates": len(funding)}
        for variant in s13.S13_VARIANTS:
            vid = variant.variant_id
            table = s13.build_table(bars, variant, start, HOLDOUT_START_MS)
            ends[vid][symbol] = session_end_exits(table)
            kw = {"funding": funding, "start_ms": start, "end_ms": HOLDOUT_START_MS}
            base = run_backtest(bars, s13.strategy(table), s13.INTERVAL_MS, costs=BASE_COSTS, **kw).trades
            hard = run_backtest(bars, s13.strategy(table), s13.INTERVAL_MS, costs=STRESS_COSTS, **kw).trades
            every[vid][symbol] = section_trades(base, None, HOLDOUT_START_MS)
            inst = sr.Instrument(bars, table, funding)
            for sec, (lo, hi) in SECTIONS.items():
                part = section_trades(base, lo, hi)
                trades[vid][sec][symbol] = part
                stress[vid][sec][symbol] = section_trades(hard, lo, hi)
                if part:
                    sim = sr.draw_pool(inst, [t.side for t in part], lo, hi, sr.pool_size(len(part), runs),
                                       rngs[(vid, sec)], BASE_COSTS, symbol)
                    pools[(vid, sec)][symbol] = [x.r for x in sim]
                print(f"{symbol} {vid} {sec}: {len(part)} trades", flush=True)
        del bars
    payload: dict = {"study": "S13", "commit": _commit(), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(all_refs), "runs": runs, "seed": sr.SEED, "symbols": info,
                     "family": "eigene Familie, kein Holdout (Protokoll 01.11.2026)", "variants": {}}
    walk = ev.walk_forward_rule(every, min(_utc_ms(*SYMBOLS[s], 1) for s in symbols), HOLDOUT_START_MS)
    payload["walk_forward"] = walk
    for vid in variants:
        row: dict = {}
        for sec in SECTIONS:
            fig = ev.section_figures(trades[vid][sec], ends[vid])
            p = random_mean = None
            if ev.needs_pvalue(fig, sec):
                counts = {s: len(ts) for s, ts in trades[vid][sec].items() if ts}
                observed = sum(t.r for ts in trades[vid][sec].values() for t in ts)
                result = sr.pvalue_from_pools(pools[(vid, sec)], counts, observed, runs, rngs[(vid, sec)])
                p, random_mean = result.p, result.random_mean
            hard = ev.section_figures(stress[vid][sec])
            row[sec] = {"figures": fig, "p": p, "random_mean_r": random_mean, "verdict": ev.section_verdict(fig, p, sec),
                        "stress_expectancy_r": hard["expectancy_r"], "stress_n": hard["n"]}
        both = {s: list(trades[vid]["train"].get(s, [])) + list(trades[vid]["validation"].get(s, [])) for s in symbols}
        row["year_stability"] = ev.year_rule(both)
        row["verdict"] = ev.final_verdict(row["train"]["verdict"], row["validation"]["verdict"], row["year_stability"], walk)
        payload["variants"][vid] = row
        print(f"{vid}: {row['verdict']}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s13_run_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=sorted) + "\n")
    (out_dir / f"s13_run_{stamp}.md").write_text(run_markdown(payload))
    print(f"written {path}")
    return 0


def _f(x: float | None, digits: int = 3) -> str:
    if x is None:
        return "–"
    if x == float("inf"):
        return "∞"
    return f"{x:.{digits}f}".replace(".", ",")


def run_markdown(p: dict) -> str:
    lines = ["# S13 Auswertung Training und Validierung (eigene Familie, kein Holdout)", "",
             (f"Commit `{p['commit']}`, Datensatz-Hash `{p['dataset_hash']}`, erstellt {p['created']}. USD-M 1m, "
              f"{', '.join(f'{s} ab {v['first_month']}' for s, v in p['symbols'].items())}, bis 2024-12. Kosten Protokoll 4.4 "
              f"mit Funding, Zufallsvergleich {p['runs']} Läufe, Seed {p['seed']}. 1 R = Abstand zum Katastrophen-Stop."), "",
             "| Variante | Abschnitt | n (n_eff) | E[R] | E[R] Zufall | p | PF | DD | E[R] doppelte Kosten | Urteil |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for vid, v in p["variants"].items():
        for sec, name in (("train", "Training"), ("validation", "Validierung")):
            r, f = v[sec], v[sec]["figures"]
            verdict = "erfüllt" if r["verdict"]["pass"] else "nicht erfüllt: " + ", ".join(r["verdict"]["reasons"])
            lines.append(f"| {vid} | {name} | {f['n']} ({f['n_eff']}) | {_f(f['expectancy_r'])} | {_f(r['random_mean_r'])} | {_f(r['p'])} | "
                         f"{_f(f['profit_factor'], 2)} | {_f(100 * f['max_drawdown_pct'], 1)} % | {_f(r['stress_expectancy_r'])} | {verdict} |")
    w = p["walk_forward"]
    lines += ["", (f"Walk-Forward 24/6 über beide Varianten: verketteter Erwartungswert {_f(w['chained_expectancy_r'])} R "
                   f"({w['windows']} Fenster, gewählt: {', '.join(w['chosen'])}), {'erfüllt' if w['pass'] else 'nicht erfüllt'}."), ""]
    for vid, v in p["variants"].items():
        lines.append(f"**{vid}: {v['verdict']}.** Jahresstabilität {'erfüllt' if v['year_stability'] else 'nicht erfüllt'}.")
    lines += ["", "## Beschreibend", "",
              "| Variante | Abschnitt | Trefferquote | Ø Gewinn / Ø Verlust R | Sitzungsende | Katastrophen-Stop | Funding R/Trade | Gebühren R/Trade | BTC E[R] (n) | Long / Short E[R] |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for vid, v in p["variants"].items():
        for sec, name in (("train", "Training"), ("validation", "Validierung")):
            f = v[sec]["figures"]
            btc = f["by_symbol"].get("BTCUSDT", {"n": 0, "expectancy_r": 0.0})
            se = f["session_end_share"]
            lines.append(f"| {vid} | {name} | {_f(100 * f['win_rate'], 1)} % | {_f(f['avg_win_r'])} / {_f(f['avg_loss_r'])} | "
                         f"{'–' if se is None else _f(100 * se, 1) + ' %'} | {_f(100 * f['catastrophe_stop_share'], 1)} % | "
                         f"{_f(f['mean_funding_r'], 4)} | {_f(f['mean_fee_r'], 4)} | {_f(btc['expectancy_r'])} ({btc['n']}) | "
                         f"{_f(f['by_side']['long']['expectancy_r'])} / {_f(f['by_side']['short']['expectancy_r'])} |")
    lines += ["", "Je Kalenderjahr (n, E[R]): " + "; ".join(
        f"{vid} " + ", ".join(f"{y} {d['n']}/{_f(d['expectancy_r'])}" for sec in ("train", "validation")
                              for y, d in v[sec]["figures"]["by_year"].items()) for vid, v in p["variants"].items()) + ".",
              "", "Nicht berechnet: die Rendite mit dem Volatilitätsziel der Studie (4.4, nur beschreibend).",
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
