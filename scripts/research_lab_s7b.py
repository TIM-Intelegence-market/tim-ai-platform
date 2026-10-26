"""Study S7b: S7 with at most one open position over BTC/ETH/SOL. Outcome-blind count
(gate), registration of the gate variants and training/validation with the portfolio cap.

    python scripts/research_lab_s7b.py count --out DIR            # lower-bound signal counts with the global 30-bar lock
    python scripts/research_lab_s7b.py register --report COUNT.json  # register the N=20 variants that passed the gate
    python scripts/research_lab_s7b.py train --out DIR [--commit-register]

Data: the S7 archives (`python scripts/research_lab_s7.py fetch`); the store refuses holdout
months (2025+). `count` writes s7b_count_<stamp>.json/.md and never computes an outcome.
`train` runs `engine.run_portfolio` (cap 1, priority BTC > ETH > SOL) for every variant,
evaluates training and validation with the S7b minimums, writes s7b_train_<stamp>.json/.md
plus the trades, and with --commit-register sets the register statuses.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.research_lab.backtest.engine import Trade, run_portfolio  # noqa: E402
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore  # noqa: E402
from src.research_lab.hypotheses import s7, s7b  # noqa: E402
from src.research_lab.protocol import (  # noqa: E402
    BASE_COSTS, HOLDOUT_START_MS, PROTOCOL_VERSION, STRESS_COSTS, UNIVERSE_LIMITATION,
)
from src.research_lab.stats.inference import month_block_bootstrap_ci, open_at_section_end, section_trades  # noqa: E402
from src.research_lab.stats.random_entry import atr_at_signal  # noqa: E402
from src.research_lab.stats.register import HypothesisRegister  # noqa: E402
from src.research_lab.studies import s7_eval as ev  # noqa: E402

# Shared helpers of the parent study (archives, sections, projection, trade records).
_spec = importlib.util.spec_from_file_location("research_lab_s7", ROOT / "scripts" / "research_lab_s7.py")
s7script = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("research_lab_s7", s7script)
_spec.loader.exec_module(s7script)

SYMBOLS = s7script.SYMBOLS
SECTIONS = s7script.SECTIONS
REGISTER = s7script.REGISTER
# Gate on the lower-bound count (every taken signal blocks all instruments for 30 bars), section 6.1 of S7b.
GATE_TRAIN = 100
GATE_TRAIN_WEEKS = 60
GATE_VALIDATION = 50
GATE_VALIDATION_WEEKS = 30
GATE_HOLDOUT = 50
GATE_HOLDOUT_WEEKS = 30
# Verdict minimums on actual trades (section 5.1/5.3 of S7b): protocol Mid asks 50 / 25 / 30.
MINIMUMS = {"train": (150, 80), "validation": (100, 50), "holdout": (50, 30)}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")


def _windows() -> dict[str, tuple[int, int]]:
    return {sym: (s7script._begin(sym), HOLDOUT_START_MS) for sym in SYMBOLS}


def _section_of(time: int, symbol: str) -> str | None:
    for section, (lo, hi) in s7script._section_windows(symbol).items():
        if lo <= time < hi:
            return section
    return None


# ----------------------------------------------------------------------------- count (gate)


def count(store: ArchiveStore, out_dir: Path) -> int:
    data = s7script.load_bars(store)
    payload: dict = {"study": s7b.HYPOTHESIS, "parent": s7b.PARENT, "protocol": "S7b 0.1 (Entwurf)",
                     "rules_commit_note": "Regelstand = commit; Änderung danach = neue Studie", "commit": s7script._commit(),
                     "outcome_blind": True, "lock": {"max_positions": s7b.MAX_POSITIONS, "priority": list(s7b.PRIORITY),
                                                     "lock_bars": s7.TIME_STOP_BARS},
                     "gate": {"train": GATE_TRAIN, "train_weeks": GATE_TRAIN_WEEKS, "validation": GATE_VALIDATION,
                              "validation_weeks": GATE_VALIDATION_WEEKS, "holdout": GATE_HOLDOUT, "holdout_weeks": GATE_HOLDOUT_WEEKS},
                     "holdout_coin_months": s7script.HOLDOUT_COIN_MONTHS, "holdout_months": s7script.HOLDOUT_MONTHS,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(s7script.all_refs()),
                     "bars": {s: len(b) for s, b in data.items()}, "coin_months_by_year": s7script.coin_months_by_year(),
                     "variants": {}}
    windows = _windows()
    for variant in s7b.S7B_VARIANTS:
        result = s7b.count_signals_locked(data, variant, windows)
        totals = {s: {"lower": 0, "weeks": 0} for s in SECTIONS}
        by_symbol = {f"{sym}/{sec}": 0 for sym in SYMBOLS for sec in SECTIONS}
        by_year_signals: dict[int, int] = {}
        by_year_weeks: dict[int, set[str]] = {}
        section_weeks: dict[str, set[str]] = {s: set() for s in SECTIONS}
        for time, symbol in result.lower_times:
            section = _section_of(time, symbol)
            if section is None:
                continue
            totals[section]["lower"] += 1
            by_symbol[f"{symbol}/{section}"] += 1
            year, week = s7.year_of(time), s7.iso_week(time)
            by_year_signals[year] = by_year_signals.get(year, 0) + 1
            by_year_weeks.setdefault(year, set()).add(week)
            section_weeks[section].add(week)
        for section in SECTIONS:
            totals[section]["weeks"] = len(section_weeks[section])
        projected, projected_weeks, weak_signal_year, weak_week_year = s7script.project(
            by_year_signals, {y: len(w) for y, w in by_year_weeks.items()})
        passes = (totals["train"]["lower"] >= GATE_TRAIN and totals["train"]["weeks"] >= GATE_TRAIN_WEEKS
                  and totals["validation"]["lower"] >= GATE_VALIDATION and totals["validation"]["weeks"] >= GATE_VALIDATION_WEEKS
                  and projected >= GATE_HOLDOUT and projected_weeks >= GATE_HOLDOUT_WEEKS)
        payload["variants"][variant.variant_id] = {
            "params": s7b.params(variant), "registrable": variant.channel in s7b.REGISTERED_CHANNELS,
            "upper_all_instruments": result.upper, "skipped_gap": result.skipped_gap, "totals": totals, "by_symbol": by_symbol,
            "by_year": {str(y): {"lower": by_year_signals.get(y, 0), "weeks": len(by_year_weeks.get(y, set()))}
                        for y in sorted(s7script.coin_months_by_year())},
            "projected_holdout_lower": round(projected, 1), "projected_holdout_weeks": round(projected_weeks, 1),
            "weakest_year_signals": weak_signal_year, "weakest_year_weeks": weak_week_year,
            "passes_gate": passes and variant.channel in s7b.REGISTERED_CHANNELS}
        print(f"{variant.variant_id:12s} train {totals['train']['lower']:5d} ({totals['train']['weeks']} Wo.)  "
              f"validation {totals['validation']['lower']:5d} ({totals['validation']['weeks']} Wo.)  "
              f"holdout {projected:7.1f} ({weak_signal_year})  weeks {projected_weeks:6.1f} ({weak_week_year})  "
              f"{'PASS' if passes else 'below gate'}{'' if variant.channel in s7b.REGISTERED_CHANNELS else ' (nur Nachbar)'}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    path = out_dir / f"s7b_count_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s7b_count_{stamp}.md").write_text(count_markdown(payload))
    print(f"written {path}")
    return 0


def count_markdown(payload: dict) -> str:
    g = payload["gate"]
    lines = ["# S7b Zähllauf (Machbarkeits-Gate, ergebnisblind, Positionsgrenze 1)", "",
             f"Commit `{payload['commit']}`, Datensatz-Hash `{payload['dataset_hash']}`, erstellt {payload['created']}. "
             f"Untere Zahl: jedes gezählte Signal sperrt alle drei Instrumente für {payload['lock']['lock_bars']} Kerzen "
             f"(Reihenfolge bei gleichem Zeitstempel {' > '.join(payload['lock']['priority'])}). Keine Ausstiege, kein R, "
             "keine Trefferquote, keine Seitenanteile.",
             f"Gate: Training ≥ {g['train']} Signale und ≥ {g['train_weeks']} Signal-Wochen, Validierung ≥ {g['validation']} und "
             f"≥ {g['validation_weeks']}, hochgerechneter Holdout ≥ {g['holdout']} Signale und ≥ {g['holdout_weeks']} Signal-Wochen "
             f"({payload['holdout_coin_months']} Coin-Monate, {payload['holdout_months']} Monate). Registrierbar sind nur die "
             "N-20-Varianten; N 55 läuft als Nachbar mit.", "",
             "| Variante | Training (untere) | Wochen | Validierung (untere) | Wochen | Holdout hochgerechnet (schwächstes Jahr) | "
             "Wochen hochgerechnet (Jahr) | alle Signale ohne Sperre | Gate |", "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for vid, v in payload["variants"].items():
        t, val = v["totals"]["train"], v["totals"]["validation"]
        verdict = "BESTANDEN" if v["passes_gate"] else ("nur Nachbar" if not v["registrable"] else "nicht bestanden")
        lines.append(f"| {vid} | {t['lower']} | {t['weeks']} | {val['lower']} | {val['weeks']} | {v['projected_holdout_lower']} "
                     f"({v['weakest_year_signals']}) | {v['projected_holdout_weeks']} ({v['weakest_year_weeks']}) | "
                     f"{v['upper_all_instruments']} | {verdict} |")
    first = next(iter(payload["variants"].values()))
    lines += ["", "## Untere Zahl je Instrument und Abschnitt", "",
              "| Variante | " + " | ".join(first["by_symbol"]) + " |", "|---|" + "---:|" * len(first["by_symbol"])]
    for vid, v in payload["variants"].items():
        lines.append(f"| {vid} | " + " | ".join(str(c) for c in v["by_symbol"].values()) + " |")
    lines += ["", "## Je Kalenderjahr (untere Zahl, Signal-Wochen)", "",
              "| Variante | " + " | ".join(f"{y} ({n} Coin-Monate)" for y, n in payload["coin_months_by_year"].items()) + " |",
              "|---|" + "---:|" * len(payload["coin_months_by_year"])]
    for vid, v in payload["variants"].items():
        lines.append(f"| {vid} | " + " | ".join(f"{b['lower']} / {b['weeks']} Wo." for b in v["by_year"].values()) + " |")
    lines += ["", "Kerzen je Instrument bis 2024-12: " + ", ".join(f"{s} {n}" for s, n in payload["bars"].items()) + ".",
              "Holdout 2025+ nicht geladen. " + UNIVERSE_LIMITATION]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- registration


def register_variants(report: Path, register_path: Path) -> int:
    """Register the N=20 variants that passed the gate in the count report."""
    payload = json.loads(report.read_text())
    register = HypothesisRegister(register_path)
    known = register.variants()
    done = 0
    for variant in s7b.GATE_VARIANTS:
        entry = payload["variants"].get(variant.variant_id)
        if entry is None or not entry["passes_gate"]:
            print(f"{variant.variant_id}: Gate nicht bestanden, nicht registriert")
            continue
        if variant.variant_id in known:
            print(f"{variant.variant_id}: bereits registriert")
            continue
        register.register(variant.variant_id, s7b.HYPOTHESIS, {**s7b.params(variant), "gate_report": report.name,
                                                                  "gate_commit": payload["commit"],
                                                                  "dataset_hash": payload["dataset_hash"]})
        done += 1
        print(f"{variant.variant_id}: registriert")
    print(f"Register: m = {register.m}")
    return 0 if done or any(v.startswith("S7b-") for v in known) else 1


# ----------------------------------------------------------------------------- training and validation


def simulate(variant: s7.S7Variant, bars_by_symbol, funding_by_symbol, costs) -> dict:
    """One portfolio run (cap 1, priority BTC > ETH > SOL) for one variant and one cost model."""
    return run_portfolio(bars_by_symbol, {sym: s7.breakout(variant) for sym in bars_by_symbol}, s7.INTERVAL_MS,
                         priority=s7b.PRIORITY, costs=costs, funding_by_symbol=funding_by_symbol,
                         start_ms_by_symbol={sym: s7script._begin(sym) for sym in bars_by_symbol}, end_ms=HOLDOUT_START_MS,
                         atr_at_signal=atr_at_signal, gap_entry_as_loss=True, max_positions=s7b.MAX_POSITIONS)


def train(store: ArchiveStore, out_dir: Path, *, runs: int = ev.BASELINE_RUNS, register_path: Path = REGISTER,
          commit_register: bool = False, progress=print) -> int:
    """Training and validation for all four S7b variants, baselines and robustness, S7b minimums.

    Unregistered variants (N = 55) are evaluated only as neighbours; they can never become candidates."""
    register = HypothesisRegister(register_path)
    registered = {v for v in register.variants() if v.startswith("S7b-")}
    if not registered:
        print("Kein S7b-Eintrag im Register: erst `register` nach Uzis Freigabe.")
        return 1
    bars_by_symbol = s7script.load_bars(store)
    bars_by_symbol = {sym: bars_by_symbol[sym] for sym in s7b.PRIORITY}
    funding_by_symbol = s7script.load_funding(store)
    atr_by_symbol = {s: ev.atr_series_contiguous(b) for s, b in bars_by_symbol.items()}
    trend_by_symbol = {s: ev.trend_series(b) for s, b in bars_by_symbol.items()}
    progress("Daten geladen: " + ", ".join(f"{s} {len(b)} Kerzen" for s, b in bars_by_symbol.items()))

    all_trades: dict[str, dict[str, list[Trade]]] = {}
    stress_trades: dict[str, dict[str, list[Trade]]] = {}
    ignored: dict[str, int] = {}
    locked: dict[str, int] = {}
    for variant in s7b.S7B_VARIANTS:
        vid = variant.variant_id
        for costs, target in ((BASE_COSTS, all_trades), (STRESS_COSTS, stress_trades)):
            results = simulate(variant, bars_by_symbol, funding_by_symbol, costs)
            target[vid] = {sym: r.trades for sym, r in results.items()}
            if costs is BASE_COSTS:
                ignored[vid] = sum(r.ignored_signals for r in results.values())
                locked[vid] = sum(r.locked_signals for r in results.values())
        progress(f"{vid}: {sum(len(t) for t in all_trades[vid].values())} Trades vor dem Holdout, "
                 f"{locked[vid]} Signale durch die Positionsgrenze verfallen")

    payload: dict = {"study": s7b.HYPOTHESIS, "parent": s7b.PARENT, "protocol": PROTOCOL_VERSION, "commit": s7script._commit(),
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(s7script.all_refs()), "random_runs": runs, "seed": ev.SEED, "holm_m": ev.HOLM_M,
                     "register_m": register.m, "registered": sorted(registered), "minimums": MINIMUMS,
                     "lock": {"max_positions": s7b.MAX_POSITIONS, "priority": list(s7b.PRIORITY)},
                     "section_rule": "Abschnittsregel 3.2 (1.2)", "universe_limitation": UNIVERSE_LIMITATION,
                     "variants": {}, "candidates": [], "walk_forward": {}}
    train_expectancy: dict[str, float] = {}
    validation_expectancy: dict[str, float] = {}
    trades_out: list[dict] = []
    for variant in s7b.S7B_VARIANTS:
        vid = variant.variant_id
        entry: dict = {"registered": vid in registered, "params": s7b.params(variant), "locked_signals": locked[vid], "sections": {}}
        for section in SECTIONS:
            by_symbol = {}
            stress_by_symbol = {}
            open_end = 0
            data_by_symbol = {}
            for symbol in bars_by_symbol:
                lo, hi = s7script._section_windows(symbol)[section]
                by_symbol[symbol] = section_trades(all_trades[vid][symbol], lo, hi)
                stress_by_symbol[symbol] = section_trades(stress_trades[vid][symbol], lo, hi)
                open_end += open_at_section_end(all_trades[vid][symbol], lo, hi)
                data_by_symbol[symbol] = ev.SectionData(bars_by_symbol[symbol], atr_by_symbol[symbol], funding_by_symbol[symbol],
                                                        lo, hi, trend_by_symbol[symbol])
            summary = ev.summarize(by_symbol, variant.target_r, ignored_signals=ignored[vid] if section == "train" else 0)
            stress = ev.summarize(stress_by_symbol, variant.target_r, costs=STRESS_COSTS)
            sec: dict = {"summary": s7script._summary_dict(summary), "stress_expectancy": stress.expectancy, "open_at_section_end": open_end}
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
                trades_out += [s7script._trade_dict(sym, t) | {"variant": vid, "section": section} for sym, ts in by_symbol.items() for t in ts]
            entry["sections"][section] = sec
            if section == "train":
                train_expectancy[vid] = summary.expectancy
        payload["variants"][vid] = entry

    pooled_by_variant = {vid: [t for _, t in ev.pooled(all_trades[vid])] for vid in all_trades}
    start_all = min(s7script._begin(s) for s in bars_by_symbol)
    wf_ok, wf_mean, wf_chosen = ev.walk_forward_rule(pooled_by_variant, start_all, HOLDOUT_START_MS)
    payload["walk_forward"] = {"pass": wf_ok, "chained_expectancy": wf_mean, "chosen": wf_chosen}
    for variant in s7b.S7B_VARIANTS:
        vid = variant.variant_id
        entry = payload["variants"][vid]
        tr = entry["sections"]["train"]
        p_a = tr.get("baselines", {}).get("A", {}).get("p", 1.0)
        p_ap = tr.get("baselines", {}).get("A'", {}).get("p", 1.0)
        summary_train = ev.summarize({sym: section_trades(all_trades[vid][sym], *s7script._section_windows(sym)["train"]) for sym in bars_by_symbol},
                                     variant.target_r, ignored_signals=ignored[vid])
        entry["training_verdict"] = ev.training_verdict(summary_train, p_a, p_ap, MINIMUMS)
        if not entry["registered"]:
            entry["status"] = "nicht registriert (nur Nachbar)"
            continue
        if not entry["training_verdict"]["pass"]:
            entry["status"] = "failed_train"
            continue
        va = entry["sections"]["validation"]
        summary_val = ev.summarize({sym: section_trades(all_trades[vid][sym], *s7script._section_windows(sym)["validation"]) for sym in bars_by_symbol},
                                   variant.target_r)
        robustness = {"Jahresstabilität": ev.year_rule(summary_train, summary_val), "Walk-Forward": wf_ok,
                      "Nachbarschaft": ev.neighbour_rule(train_expectancy, variant, s7b.S7B_VARIANTS)}
        entry["validation_verdict"] = ev.validation_verdict(summary_val, va.get("baselines", {}).get("A", {}).get("p", 1.0),
                                                            va.get("baselines", {}).get("A'", {}).get("p", 1.0), robustness, MINIMUMS)
        entry["robustness"] = robustness
        if entry["validation_verdict"]["pass"]:
            validation_expectancy[vid] = summary_val.expectancy
            entry["status"] = "validated"
        else:
            entry["status"] = "failed_validation"
    candidates = ev.select_candidates(validation_expectancy, s7b.S7B_VARIANTS)
    for vid in validation_expectancy:
        payload["variants"][vid]["status"] = "candidate" if vid in candidates else "not_selected"
    payload["candidates"] = candidates

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _stamp()
    (out_dir / f"s7b_train_{stamp}.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    (out_dir / f"s7b_train_{stamp}_trades.json").write_text(json.dumps(trades_out, ensure_ascii=False) + "\n")
    (out_dir / f"s7b_train_{stamp}.md").write_text(train_markdown(payload))
    progress(f"written {out_dir / f's7b_train_{stamp}.md'}; Kandidaten: {', '.join(candidates) or 'keine'}")
    if commit_register:
        for vid, entry in payload["variants"].items():
            if entry["registered"] and entry["status"] in ("failed_train", "failed_validation", "candidate", "not_selected"):
                note = "; ".join(entry.get("validation_verdict", entry["training_verdict"]).get("reasons", []))
                register.set_status(vid, entry["status"], note)
        progress("Register-Status geschrieben")
    return 0


def train_markdown(payload: dict) -> str:
    _f, _pct = s7script._f, s7script._pct
    m = payload["minimums"]
    lines = [f"# S7b Training und Validierung ({payload['created']})", "",
             f"Commit `{payload['commit']}`, Datensatz-Hash `{payload['dataset_hash']}`, Protokoll {payload['protocol']}, "
             f"Zufallsvergleiche {payload['random_runs']} Läufe (Seed {payload['seed']}), Holm m = {payload['holm_m']} "
             f"(Register {payload['register_m']}). Registriert: {', '.join(payload['registered']) or 'keine'}. "
             f"Positionsgrenze {payload['lock']['max_positions']} über {', '.join(payload['lock']['priority'])} "
             f"(Reihenfolge bei gleichem Zeitstempel). Mindestzahlen (Trades / Signal-Wochen): Training {m['train'][0]} / {m['train'][1]}, "
             f"Validierung {m['validation'][0]} / {m['validation'][1]}, Holdout {m['holdout'][0]} / {m['holdout'][1]}. "
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
                         f"{_f(b.get('A', {}).get('p'), 4)} | {_f(b.get('A', {}).get('expectancy'))} | {_f(b.get(s7script.A_PRIME, {}).get('p'), 4)} | "
                         f"{_f(b.get('C', {}).get('p'), 4)} | {_f(b.get('B', {}).get('expectancy'))} | {_pct(b.get('B', {}).get('hit_rate'))} | "
                         f"{reasons} | {sec['open_at_section_end']} |")
        lines.append("")
    lines += ["## Urteile", "", "| Variante | Status | Training | Validierung | Robustheit | durch Positionsgrenze verfallene Signale |",
              "|---|---|---|---|---|---:|"]
    for vid, entry in payload["variants"].items():
        tv = entry["training_verdict"]
        vv = entry.get("validation_verdict")
        rob = entry.get("robustness")
        lines.append(f"| {vid} | {entry['status']} | {'bestanden' if tv['pass'] else 'nicht bestanden: ' + '; '.join(tv['reasons'])} | "
                     f"{'–' if vv is None else ('bestanden' if vv['pass'] else 'nicht bestanden: ' + '; '.join(vv['reasons']))} | "
                     f"{'–' if rob is None else ', '.join(f'{k} {'ok' if v else 'nein'}' for k, v in rob.items())} | {entry['locked_signals']} |")
    wf = payload["walk_forward"]
    lines += ["", f"Walk-Forward 24/6 über alle vier Varianten (mit Positionsgrenze): verketteter Test-E[R] {_f(wf['chained_expectancy'])} "
              f"({'bestanden' if wf['pass'] else 'nicht bestanden'}); gewählt je Fenster: {', '.join(wf['chosen']) or '–'}.",
              f"Kandidaten für den Holdout: {', '.join(payload['candidates']) or 'keine'}.", "",
              "Kaufen-und-Halten je Instrument und Abschnitt (Long, berichtet): " + "; ".join(
                  f"{section} " + ", ".join(f"{sym} {_pct(v)}" for sym, v in next(iter(payload["variants"].values()))["sections"][section].get("buy_and_hold", {}).items())
                  for section in SECTIONS) + ".", "",
              "Trefferquote, p* und Untergrenze sind Bericht, kein Kriterium (K6). Ableitung aus S7: Training und Validierung sind "
              "durch die S7-Ergebnisse vorbelastet (Präregistrierung S7b, Abschnitt 10); der Holdout 2025+ ist unberührt. "
              + payload["universe_limitation"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["count", "register", "train"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    parser.add_argument("--report", type=Path, help="count report (JSON) for `register`")
    parser.add_argument("--register", type=Path, default=REGISTER)
    parser.add_argument("--random-runs", type=int, default=ev.BASELINE_RUNS)
    parser.add_argument("--commit-register", action="store_true", help="write the final statuses into the register")
    args = parser.parse_args(argv)
    store = ArchiveStore(args.root)
    if args.command == "count":
        return count(store, args.out)
    if args.command == "register":
        if args.report is None:
            parser.error("register needs --report")
        return register_variants(args.report, args.register)
    return train(store, args.out, runs=args.random_runs, register_path=args.register, commit_register=args.commit_register)


if __name__ == "__main__":
    raise SystemExit(main())
