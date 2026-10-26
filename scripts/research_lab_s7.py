"""Study S7: fetch the 4h archives, run the outcome-blind feasibility count (section 6.1),
register the gate variants and run training/validation (sections 5.1, 5.4, 7).

    python scripts/research_lab_s7.py fetch                       # USD-M 4h klines + funding, BTC/ETH/SOL, up to 2024-12
    python scripts/research_lab_s7.py count --out DIR             # signal counts only, no exits, no R, no hit rate
    python scripts/research_lab_s7.py register --report COUNT.json   # register the variants that passed the gate
    python scripts/research_lab_s7.py train --out DIR [--commit-register]

Needs network access to data.binance.vision for `fetch` (run on the Mac). Holdout
months (2025+) are refused by the store. `count` writes s7_count_<stamp>.json and .md
with commit, dataset hashes and per-variant counts; it never computes an outcome.
`train` evaluates every variant on training and validation (unregistered ones only as
neighbours), writes s7_train_<stamp>.json/.md plus the trades, and with
--commit-register sets the register statuses.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.backtest.engine import Trade, run_backtest  # noqa: E402
from src.research_lab.data.archive import ArchiveRef, Dataset, Market  # noqa: E402
from src.research_lab.data.parse import check_completeness  # noqa: E402
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months  # noqa: E402
from src.research_lab.hypotheses import s7  # noqa: E402
from src.research_lab.protocol import (  # noqa: E402
    BASE_COSTS, HOLDOUT_START_MS, PROTOCOL_VERSION, STRESS_COSTS, UNIVERSE_LIMITATION, VALIDATION_START_MS, _utc_ms,
)
from src.research_lab.stats.inference import month_block_bootstrap_ci, open_at_section_end, section_trades  # noqa: E402
from src.research_lab.stats.random_entry import atr_at_signal  # noqa: E402
from src.research_lab.stats.register import HypothesisRegister  # noqa: E402
from src.research_lab.studies import s7_eval as ev  # noqa: E402

LAST_MONTH = (2024, 12)
# First archive month (warm-up) and first counted month per instrument, section 3.
SYMBOLS = {"BTCUSDT": ((2020, 1), (2020, 1)), "ETHUSDT": ((2020, 1), (2020, 1)), "SOLUSDT": ((2020, 9), (2020, 10))}
HOLDOUT_MONTHS = 21  # 2025-01 .. 2026-09
HOLDOUT_COIN_MONTHS = 3 * HOLDOUT_MONTHS
GATE_TRAIN = 200
GATE_TRAIN_WEEKS = 100
GATE_VALIDATION = 100
GATE_VALIDATION_WEEKS = 50
GATE_HOLDOUT = 100
GATE_HOLDOUT_WEEKS = 60
SECTIONS = ("train", "validation")
REGISTER = Path("docs/research_lab/REGISTER.jsonl")


def refs(symbol: str, dataset: Dataset) -> list[ArchiveRef]:
    first, _ = SYMBOLS[symbol]
    interval = s7.INTERVAL if dataset is Dataset.KLINES else None
    return [ArchiveRef(Market.USDM, dataset, y, m, interval, symbol=symbol) for y, m in months(first, LAST_MONTH)]


def all_refs() -> list[ArchiveRef]:
    out: list[ArchiveRef] = []
    for symbol in SYMBOLS:
        out += refs(symbol, Dataset.KLINES) + refs(symbol, Dataset.FUNDING)
    return out


def fetch(store: ArchiveStore) -> int:
    ok = True
    for ref in all_refs():
        store.fetch(ref)
        if ref.dataset is Dataset.KLINES:
            report = check_completeness(store.load_klines([ref]), s7.INTERVAL_MS, ref.start_ms, ref.end_ms)
            if report.missing or report.duplicates or report.out_of_order:
                print(f"{ref.filename}: {report.present}/{report.expected}, missing {report.missing}, "
                      f"duplicates {report.duplicates}, out of order {report.out_of_order}")
            ok = ok and report.duplicates == 0 and report.out_of_order == 0
    print(f"{len(all_refs())} archives verified, dataset hash {store.dataset_hash(all_refs())}")
    return 0 if ok else 1


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def load_bars(store: ArchiveStore) -> dict[str, list]:
    """Bars per instrument before the holdout; the store refuses later months anyway."""
    return {symbol: [b for b in store.load_klines(refs(symbol, Dataset.KLINES)) if b.open_time < HOLDOUT_START_MS]
            for symbol in SYMBOLS}


def coin_months_by_year() -> dict[int, int]:
    out: dict[int, int] = {}
    for _, start in SYMBOLS.values():
        for y, _m in months(start, LAST_MONTH):
            out[y] = out.get(y, 0) + 1
    return out


def project(by_year_signals: dict[int, int], by_year_weeks: dict[int, int]) -> tuple[float, float, int, int]:
    """Holdout projection from the weakest calendar year (section 6.1): signals per coin-month x 63,
    signal weeks per calendar month x 21. The weakest year is chosen separately for each figure."""
    coin_months = coin_months_by_year()
    years = sorted(coin_months)
    signal_density = {y: by_year_signals.get(y, 0) / coin_months[y] for y in years}
    week_density = {y: by_year_weeks.get(y, 0) / 12 for y in years}
    weakest_signal = min(years, key=lambda y: (signal_density[y], y))
    weakest_week = min(years, key=lambda y: (week_density[y], y))
    return (signal_density[weakest_signal] * HOLDOUT_COIN_MONTHS, week_density[weakest_week] * HOLDOUT_MONTHS,
            weakest_signal, weakest_week)


def count(store: ArchiveStore, out_dir: Path) -> int:
    data = load_bars(store)
    payload: dict = {"study": "S7", "protocol": "S7 0.2 (Entwurf)", "rules_commit_note": "Regelstand = commit; Änderung danach = neue Studie", "commit": _commit(), "outcome_blind": True,
                     "gate": {"train": GATE_TRAIN, "train_weeks": GATE_TRAIN_WEEKS, "validation": GATE_VALIDATION,
                              "validation_weeks": GATE_VALIDATION_WEEKS, "holdout": GATE_HOLDOUT,
                              "holdout_weeks": GATE_HOLDOUT_WEEKS},
                     "holdout_coin_months": HOLDOUT_COIN_MONTHS, "holdout_months": HOLDOUT_MONTHS,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(all_refs()),
                     "dataset_hashes": {s: store.dataset_hash(refs(s, Dataset.KLINES)) for s in SYMBOLS},
                     "bars": {s: len(b) for s, b in data.items()}, "coin_months_by_year": coin_months_by_year(),
                     "variants": {}}
    for variant in s7.S7_VARIANTS:
        rows: dict[str, dict] = {}
        totals = {s: {"upper": 0, "lower": 0, "weeks": 0} for s in SECTIONS}
        by_year_signals: dict[int, int] = {}
        by_year_weeks: dict[int, set[str]] = {}
        section_weeks: dict[str, set[str]] = {s: set() for s in SECTIONS}
        for symbol, bars in data.items():
            begin = _utc_ms(SYMBOLS[symbol][1][0], SYMBOLS[symbol][1][1], 1)
            for section, (lo, hi) in {"train": (begin, VALIDATION_START_MS),
                                      "validation": (max(begin, VALIDATION_START_MS), HOLDOUT_START_MS)}.items():
                result = s7.count_signals(bars, variant, lo, hi)
                rows[f"{symbol}/{section}"] = {"upper": result.upper, "lower": result.lower, "skipped_gap": result.skipped_gap}
                totals[section]["upper"] += result.upper
                totals[section]["lower"] += result.lower
                for time in result.lower_times:
                    year, week = s7.year_of(time), s7.iso_week(time)
                    by_year_signals[year] = by_year_signals.get(year, 0) + 1
                    by_year_weeks.setdefault(year, set()).add(week)
                    section_weeks[section].add(week)
        for section in SECTIONS:
            totals[section]["weeks"] = len(section_weeks[section])
        projected, projected_weeks, weak_signal_year, weak_week_year = project(
            by_year_signals, {y: len(w) for y, w in by_year_weeks.items()})
        passes = (totals["train"]["lower"] >= GATE_TRAIN and totals["train"]["weeks"] >= GATE_TRAIN_WEEKS
                  and totals["validation"]["lower"] >= GATE_VALIDATION and totals["validation"]["weeks"] >= GATE_VALIDATION_WEEKS
                  and projected >= GATE_HOLDOUT and projected_weeks >= GATE_HOLDOUT_WEEKS)
        payload["variants"][variant.variant_id] = {
            "params": variant.params, "counts": rows, "totals": totals,
            "by_year": {str(y): {"lower": by_year_signals.get(y, 0), "weeks": len(by_year_weeks.get(y, set()))}
                        for y in sorted(coin_months_by_year())},
            "projected_holdout_lower": round(projected, 1), "projected_holdout_weeks": round(projected_weeks, 1),
            "weakest_year_signals": weak_signal_year, "weakest_year_weeks": weak_week_year, "passes_gate": passes}
        print(f"{variant.variant_id:12s} train {totals['train']['lower']:5d}  validation {totals['validation']['lower']:5d}  "
              f"holdout {projected:7.1f} ({weak_signal_year})  weeks {projected_weeks:6.1f} ({weak_week_year})  "
              f"{'PASS' if passes else 'below gate'}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s7_count_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s7_count_{stamp}.md").write_text(count_markdown(payload))
    print(f"written {path}")
    return 0


def count_markdown(payload: dict) -> str:
    lines = ["# S7 Zähllauf (Machbarkeits-Gate 6.1, ergebnisblind)", "",
             f"Commit `{payload['commit']}`, Datensatz-Hash `{payload['dataset_hash']}`, erstellt {payload['created']}.",
             f"Gate: Training ≥ {payload['gate']['train']} Signale und ≥ {payload['gate']['train_weeks']} Signal-Wochen, "
             f"Validierung ≥ {payload['gate']['validation']} und ≥ {payload['gate']['validation_weeks']}, hochgerechneter Holdout "
             f"≥ {payload['gate']['holdout']} Signale und ≥ {payload['gate']['holdout_weeks']} Signal-Wochen "
             f"({payload['holdout_coin_months']} Coin-Monate, {payload['holdout_months']} Monate). Untere Zahl: jeder Trade "
             "läuft bis zum Zeitstop (30 Kerzen). Keine Ausstiege, kein R, keine Trefferquote, keine Seitenanteile.", "",
             "| Variante | Training (untere/obere) | Validierung (untere/obere) | Signal-Wochen T/V | Holdout hochgerechnet "
             "(schwächstes Jahr) | Wochen hochgerechnet (Jahr) | Gate |", "|---|---:|---:|---:|---:|---:|---|"]
    for vid, v in payload["variants"].items():
        t, val = v["totals"]["train"], v["totals"]["validation"]
        lines.append(f"| {vid} | {t['lower']} / {t['upper']} | {val['lower']} / {val['upper']} | {t['weeks']} / {val['weeks']} | "
                     f"{v['projected_holdout_lower']} ({v['weakest_year_signals']}) | {v['projected_holdout_weeks']} "
                     f"({v['weakest_year_weeks']}) | {'BESTANDEN' if v['passes_gate'] else 'nicht bestanden'} |")
    lines += ["", "## Je Instrument und Abschnitt (untere Zahl / obere Zahl / Signale mit Lücke im Fenster)", "",
              "| Variante | " + " | ".join(next(iter(payload["variants"].values()))["counts"]) + " |",
              "|---|" + "---:|" * len(next(iter(payload["variants"].values()))["counts"])]
    for vid, v in payload["variants"].items():
        lines.append(f"| {vid} | " + " | ".join(f"{c['lower']} / {c['upper']} / {c['skipped_gap']}" for c in v["counts"].values()) + " |")
    lines += ["", "## Je Kalenderjahr (untere Zahl gepoolt über BTC/ETH/SOL, Signal-Wochen)", "",
              "| Variante | " + " | ".join(f"{y} ({n} Coin-Monate)" for y, n in payload["coin_months_by_year"].items()) + " |",
              "|---|" + "---:|" * len(payload["coin_months_by_year"])]
    for vid, v in payload["variants"].items():
        lines.append(f"| {vid} | " + " | ".join(f"{b['lower']} / {b['weeks']} Wo." for b in v["by_year"].values()) + " |")
    lines += ["", f"Kerzen je Instrument bis 2024-12: " + ", ".join(f"{s} {n}" for s, n in payload["bars"].items()) + ".",
              "Holdout 2025+ nicht geladen. Universum BTCUSDT/ETHUSDT/SOLUSDT, 2026 mit Wissen um das Überleben gewählt "
              "(Survivorship-Grenze, Protokoll 3.1)."]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- registration (P4) and training (P5)


def register_variants(report: Path, register_path: Path) -> int:
    """Register the variants that passed the gate in the count report (section 6.1)."""
    payload = json.loads(report.read_text())
    register = HypothesisRegister(register_path)
    known = register.variants()
    done = 0
    for variant in s7.S7_VARIANTS:
        entry = payload["variants"].get(variant.variant_id)
        if entry is None or not entry["passes_gate"]:
            print(f"{variant.variant_id}: Gate nicht bestanden, nicht registriert")
            continue
        if variant.variant_id in known:
            print(f"{variant.variant_id}: bereits registriert")
            continue
        register.register(variant.variant_id, s7.HYPOTHESIS, {**variant.params, "gate_report": report.name,
                                                                 "gate_commit": payload["commit"],
                                                                 "dataset_hash": payload["dataset_hash"]})
        done += 1
        print(f"{variant.variant_id}: registriert")
    print(f"Register: m = {register.m}")
    return 0 if done or known else 1


def _begin(symbol: str) -> int:
    return _utc_ms(SYMBOLS[symbol][1][0], SYMBOLS[symbol][1][1], 1)


def load_funding(store: ArchiveStore) -> dict[str, list]:
    return {symbol: store.load_funding(refs(symbol, Dataset.FUNDING)) for symbol in SYMBOLS}


def _trade_dict(symbol: str, t: Trade) -> dict:
    return {"symbol": symbol, "signal_time": t.signal_time, "entry_time": t.entry_time, "exit_time": t.exit_time, "side": t.side,
            "entry": t.entry_price, "exit": t.exit_price, "stop": t.stop, "reason": t.reason, "bars_held": t.bars_held,
            "r": t.r, "cost_r": t.cost_r, "funding_r": t.funding_r, "stop_atr": t.stop_atr, "target_r": t.target_r,
            "hit": ev.is_hit(t)}


def _summary_dict(s: ev.Summary) -> dict:
    return dataclasses.asdict(s)


def _section_windows(symbol: str) -> dict[str, tuple[int, int]]:
    begin = _begin(symbol)
    return {"train": (begin, VALIDATION_START_MS), "validation": (max(begin, VALIDATION_START_MS), HOLDOUT_START_MS)}


def train(store: ArchiveStore, out_dir: Path, *, runs: int = ev.BASELINE_RUNS, register_path: Path = REGISTER,
          commit_register: bool = False, progress=print) -> int:
    """Training and validation for all four variants (section 5.1), baselines (7), robustness (5.4).

    Unregistered variants are evaluated only as neighbours (5.4); they can never become candidates."""
    register = HypothesisRegister(register_path)
    registered = {v for v, e in register.variants().items() if v.startswith("S7-")}
    if not registered:
        print("Kein S7-Eintrag im Register: erst `register` nach Uzis Freigabe (Abschnitt 6.1/8).")
        return 1
    bars_by_symbol = load_bars(store)
    funding_by_symbol = load_funding(store)
    atr_by_symbol = {s: ev.atr_series_contiguous(b) for s, b in bars_by_symbol.items()}
    trend_by_symbol = {s: ev.trend_series(b) for s, b in bars_by_symbol.items()}
    progress("Daten geladen: " + ", ".join(f"{s} {len(b)} Kerzen" for s, b in bars_by_symbol.items()))

    all_trades: dict[str, dict[str, list[Trade]]] = {}  # variant -> symbol -> all trades before the holdout
    stress_trades: dict[str, dict[str, list[Trade]]] = {}
    ignored: dict[str, int] = {}
    for variant in s7.S7_VARIANTS:
        all_trades[variant.variant_id], stress_trades[variant.variant_id] = {}, {}
        ignored[variant.variant_id] = 0
        for symbol, bars in bars_by_symbol.items():
            for costs, target in ((BASE_COSTS, all_trades), (STRESS_COSTS, stress_trades)):
                result = run_backtest(bars, s7.breakout(variant), s7.INTERVAL_MS, costs=costs, funding=funding_by_symbol[symbol],
                                      start_ms=_begin(symbol), end_ms=HOLDOUT_START_MS, atr_at_signal=atr_at_signal,
                                      gap_entry_as_loss=True)
                target[variant.variant_id][symbol] = result.trades
                if costs is BASE_COSTS:
                    ignored[variant.variant_id] += result.ignored_signals
        progress(f"{variant.variant_id}: {sum(len(t) for t in all_trades[variant.variant_id].values())} Trades vor dem Holdout")

    payload: dict = {"study": "S7", "protocol": PROTOCOL_VERSION, "commit": _commit(), "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(all_refs()), "random_runs": runs, "seed": ev.SEED, "holm_m": ev.HOLM_M,
                     "register_m": register.m, "registered": sorted(registered), "section_rule": "Abschnittsregel 3.2 (1.2)",
                     "universe_limitation": UNIVERSE_LIMITATION, "variants": {}, "candidates": [], "walk_forward": {}}
    train_expectancy: dict[str, float] = {}
    validation_expectancy: dict[str, float] = {}
    trades_out: list[dict] = []
    for variant in s7.S7_VARIANTS:
        vid = variant.variant_id
        entry: dict = {"registered": vid in registered, "params": variant.params, "sections": {}}
        for section in SECTIONS:
            by_symbol = {}
            stress_by_symbol = {}
            open_end = 0
            data_by_symbol = {}
            for symbol in SYMBOLS:
                lo, hi = _section_windows(symbol)[section]
                by_symbol[symbol] = section_trades(all_trades[vid][symbol], lo, hi)
                stress_by_symbol[symbol] = section_trades(stress_trades[vid][symbol], lo, hi)
                open_end += open_at_section_end(all_trades[vid][symbol], lo, hi)
                data_by_symbol[symbol] = ev.SectionData(bars_by_symbol[symbol], atr_by_symbol[symbol], funding_by_symbol[symbol],
                                                        lo, hi, trend_by_symbol[symbol])
            summary = ev.summarize(by_symbol, variant.target_r, ignored_signals=ignored[vid] if section == "train" else 0)
            stress = ev.summarize(stress_by_symbol, variant.target_r, costs=STRESS_COSTS)
            sec: dict = {"summary": _summary_dict(summary), "stress_expectancy": stress.expectancy, "open_at_section_end": open_end}
            if summary.n:
                baselines = {}
                for mode in ev.MODES:
                    b = ev.random_baseline(data_by_symbol, by_symbol, mode=mode, runs=runs)
                    baselines[mode] = {"p": b.p, "expectancy": b.mean_expectancy, "hit_rate": b.hit_rate, "pool_sizes": b.pool_sizes}
                    progress(f"{vid} {section} Baseline {mode}: p = {b.p:.4f}, E = {b.mean_expectancy:+.3f}")
                baselines["B"] = ev.baseline_summary(ev.mirrored(data_by_symbol, by_symbol))
                sec["baselines"] = baselines
                sec["buy_and_hold"] = {sym: ev.buy_and_hold(d) for sym, d in data_by_symbol.items()}
                pooled = [t for _, t in ev.pooled(by_symbol)]
                sec["bootstrap_ci_95"] = month_block_bootstrap_ci(pooled, seed=ev.SEED + 7)
                trades_out += [_trade_dict(sym, t) | {"variant": vid, "section": section} for sym, ts in by_symbol.items() for t in ts]
            entry["sections"][section] = sec
            if section == "train":
                train_expectancy[vid] = summary.expectancy
        payload["variants"][vid] = entry

    # verdicts, protocol 8 order: training first, validation only for registered variants that passed
    pooled_by_variant = {vid: [t for _, t in ev.pooled(all_trades[vid])] for vid in all_trades}
    start_all = min(_begin(s) for s in SYMBOLS)
    wf_ok, wf_mean, wf_chosen = ev.walk_forward_rule(pooled_by_variant, start_all, HOLDOUT_START_MS)
    payload["walk_forward"] = {"pass": wf_ok, "chained_expectancy": wf_mean, "chosen": wf_chosen}
    for variant in s7.S7_VARIANTS:
        vid = variant.variant_id
        entry = payload["variants"][vid]
        tr = entry["sections"]["train"]
        p_a = tr.get("baselines", {}).get("A", {}).get("p", 1.0)
        p_ap = tr.get("baselines", {}).get("A'", {}).get("p", 1.0)
        summary_train = ev.summarize({sym: section_trades(all_trades[vid][sym], *_section_windows(sym)["train"]) for sym in SYMBOLS},
                                     variant.target_r, ignored_signals=ignored[vid])
        entry["training_verdict"] = ev.training_verdict(summary_train, p_a, p_ap)
        if not entry["registered"]:
            entry["status"] = "nicht registriert (nur Nachbar)"
            continue
        if not entry["training_verdict"]["pass"]:
            entry["status"] = "failed_train"
            continue
        va = entry["sections"]["validation"]
        summary_val = ev.summarize({sym: section_trades(all_trades[vid][sym], *_section_windows(sym)["validation"]) for sym in SYMBOLS},
                                   variant.target_r)
        robustness = {"Jahresstabilität": ev.year_rule(summary_train, summary_val), "Walk-Forward": wf_ok,
                      "Nachbarschaft": ev.neighbour_rule(train_expectancy, variant, s7.S7_VARIANTS)}
        entry["validation_verdict"] = ev.validation_verdict(summary_val, va.get("baselines", {}).get("A", {}).get("p", 1.0),
                                                            va.get("baselines", {}).get("A'", {}).get("p", 1.0), robustness)
        entry["robustness"] = robustness
        if entry["validation_verdict"]["pass"]:
            validation_expectancy[vid] = summary_val.expectancy
            entry["status"] = "validated"
        else:
            entry["status"] = "failed_validation"
    candidates = ev.select_candidates(validation_expectancy, s7.S7_VARIANTS)
    for vid in validation_expectancy:
        payload["variants"][vid]["status"] = "candidate" if vid in candidates else "not_selected"
    payload["candidates"] = candidates

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    (out_dir / f"s7_train_{stamp}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    (out_dir / f"s7_train_{stamp}_trades.json").write_text(json.dumps(trades_out, ensure_ascii=False) + "\n")
    (out_dir / f"s7_train_{stamp}.md").write_text(train_markdown(payload))
    progress(f"written {out_dir / f's7_train_{stamp}.md'}; Kandidaten: {', '.join(candidates) or 'keine'}")
    if commit_register:
        for vid, entry in payload["variants"].items():
            if entry["registered"] and entry["status"] in ("failed_train", "failed_validation", "candidate", "not_selected"):
                note = "; ".join(entry.get("validation_verdict", entry["training_verdict"]).get("reasons", []))
                register.set_status(vid, entry["status"], note)
        progress("Register-Status geschrieben")
    return 0


A_PRIME = "A'"


def _f(value, digits: int = 3) -> str:
    if value is None:
        return "–"
    if isinstance(value, float) and value == float("inf"):
        return "∞"
    return f"{value:.{digits}f}".replace(".", ",")


def _pct(value) -> str:
    return "–" if value is None else f"{100 * value:.1f} %".replace(".", ",")


def train_markdown(payload: dict) -> str:
    lines = [f"# S7 Training und Validierung ({payload['created']})", "",
             f"Commit `{payload['commit']}`, Datensatz-Hash `{payload['dataset_hash']}`, Protokoll {payload['protocol']}, "
             f"Zufallsvergleiche {payload['random_runs']} Läufe (Seed {payload['seed']}), Holm m = {payload['holm_m']} "
             f"(Register {payload['register_m']}). Registriert: {', '.join(payload['registered']) or 'keine'}. "
             f"{payload['section_rule']}. Holdout nicht geladen.", ""]
    for section in SECTIONS:
        lines += [f"## {'Training' if section == 'train' else 'Validierung'}", "",
                  "| Variante | n | Wochen | E[R] | 95-%-CI (Monatsblock) | PF | Treffer | p* | Untergrenze | DD (R) | Stress E | "
                  "p(A) | E(A) | p(A′) | p(C) | E(B) | Treffer(B) | Ausstiege | offen |", "|---|" + "---:|" * 18]
        for vid, entry in payload["variants"].items():
            sec = entry["sections"][section]
            s = sec["summary"]
            b = sec.get("baselines", {})
            ci = sec.get("bootstrap_ci_95")
            reasons = ", ".join(f"{k} {v}" for k, v in s["by_reason"].items())
            lines.append(f"| {vid}{'' if entry['registered'] else ' (nur Nachbar)'} | {s['n']} | {s['signal_weeks']} | {_f(s['expectancy'])} | "
                         f"{'–' if not ci else _f(ci[0]) + ' … ' + _f(ci[1])} | {_f(s['profit_factor'], 2)} | {_pct(s['hit_rate'])} | "
                         f"{_pct(s['p_star'])} | {_pct(s['hit_lower_bound'])} | {_f(s['max_drawdown'], 1)} | {_f(sec['stress_expectancy'])} | "
                         f"{_f(b.get('A', {}).get('p'), 4)} | {_f(b.get('A', {}).get('expectancy'))} | {_f(b.get(A_PRIME, {}).get('p'), 4)} | "
                         f"{_f(b.get('C', {}).get('p'), 4)} | {_f(b.get('B', {}).get('expectancy'))} | {_pct(b.get('B', {}).get('hit_rate'))} | "
                         f"{reasons} | {sec['open_at_section_end']} |")
        lines.append("")
    lines += ["## Urteile", "", "| Variante | Status | Training | Validierung | Robustheit |", "|---|---|---|---|---|"]
    for vid, entry in payload["variants"].items():
        tv = entry["training_verdict"]
        vv = entry.get("validation_verdict")
        rob = entry.get("robustness")
        lines.append(f"| {vid} | {entry['status']} | {'bestanden' if tv['pass'] else 'nicht bestanden: ' + '; '.join(tv['reasons'])} | "
                     f"{'–' if vv is None else ('bestanden' if vv['pass'] else 'nicht bestanden: ' + '; '.join(vv['reasons']))} | "
                     f"{'–' if rob is None else ', '.join(f'{k} {'ok' if v else 'nein'}' for k, v in rob.items())} |")
    wf = payload["walk_forward"]
    lines += ["", f"Walk-Forward 24/6 über alle vier Varianten: verketteter Test-E[R] {_f(wf['chained_expectancy'])} "
              f"({'bestanden' if wf['pass'] else 'nicht bestanden'}); gewählt je Fenster: {', '.join(wf['chosen']) or '–'}.",
              f"Kandidaten für den Holdout: {', '.join(payload['candidates']) or 'keine'}.", "",
              "Kaufen-und-Halten je Instrument und Abschnitt (Long, berichtet): " + "; ".join(
                  f"{section} " + ", ".join(f"{sym} {_pct(v)}" for sym, v in next(iter(payload["variants"].values()))["sections"][section].get("buy_and_hold", {}).items())
                  for section in SECTIONS) + ".", "",
              "Trefferquote, p* und Untergrenze sind Bericht, kein Kriterium (Präregistrierung 2.1/K6). "
              + payload["universe_limitation"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["fetch", "count", "register", "train"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    parser.add_argument("--report", type=Path, help="count report (JSON) for `register`")
    parser.add_argument("--register", type=Path, default=REGISTER)
    parser.add_argument("--random-runs", type=int, default=ev.BASELINE_RUNS)
    parser.add_argument("--commit-register", action="store_true", help="write the final statuses into the register")
    args = parser.parse_args(argv)
    store = ArchiveStore(args.root)
    if args.command == "fetch":
        return fetch(store)
    if args.command == "count":
        return count(store, args.out)
    if args.command == "register":
        if args.report is None:
            parser.error("register needs --report")
        return register_variants(args.report, args.register)
    return train(store, args.out, runs=args.random_runs, register_path=args.register, commit_register=args.commit_register)


if __name__ == "__main__":
    raise SystemExit(main())
