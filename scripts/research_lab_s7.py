"""Study S7: fetch the 4h archives and run the outcome-blind feasibility count (section 6.1).

    python scripts/research_lab_s7.py fetch            # USD-M 4h klines + funding, BTC/ETH/SOL, up to 2024-12
    python scripts/research_lab_s7.py count --out DIR  # signal counts only, no exits, no R, no hit rate

Needs network access to data.binance.vision for `fetch` (run on the Mac). Holdout
months (2025+) are refused by the store. `count` writes s7_count_<stamp>.json and .md
with commit, dataset hashes and per-variant counts; it never computes an outcome.
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
from src.research_lab.data.parse import check_completeness  # noqa: E402
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months  # noqa: E402
from src.research_lab.hypotheses import s7  # noqa: E402
from src.research_lab.protocol import HOLDOUT_START_MS, VALIDATION_START_MS, _utc_ms  # noqa: E402

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["fetch", "count"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    args = parser.parse_args(argv)
    store = ArchiveStore(args.root)
    return fetch(store) if args.command == "fetch" else count(store, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
