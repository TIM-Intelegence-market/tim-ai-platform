"""Study S9: fetch BTCUSDT 15m archives, run the outcome-blind feasibility count, then training/validation.

    python scripts/research_lab_s9.py fetch                 # USD-M 15m klines + funding, BTCUSDT, 2020-01 .. 2024-12
    python scripts/research_lab_s9.py count --out DIR       # signal counts only, no exits, no R
    python scripts/research_lab_s9.py train --out DIR       # protocol K-criteria on training and validation

Needs network access to data.binance.vision for `fetch` (run on the Mac). Holdout months
(2025+) are refused by the store and never requested here. `train` runs only the variants
that passed the gate of the newest count report in --out (or all with --all-variants, which
the report then states).
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
from src.research_lab.hypotheses import s9  # noqa: E402
from src.research_lab.protocol import HOLDOUT_START_MS, MIN_TRADES_HOLDOUT, MIN_TRADES_TRAIN, VALIDATION_START_MS, _utc_ms  # noqa: E402
from src.research_lab.runner import RunConfig, run, write_report  # noqa: E402

FIRST, LAST = (2020, 1), (2024, 12)
SIGNALS_MS = _utc_ms(2020, 1, 1)
GATE_TRAIN = MIN_TRADES_TRAIN["short"]  # 500
GATE_VALIDATION = MIN_TRADES_TRAIN["short"] // 2  # 250
GATE_HOLDOUT = MIN_TRADES_HOLDOUT["short"]  # 200
HOLDOUT_MONTHS = 21  # 2025-01 .. 2026-09


def kline_refs() -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, s9.INTERVAL) for y, m in months(FIRST, LAST)]


def funding_refs() -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.FUNDING, y, m) for y, m in months(FIRST, LAST)]


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def fetch(store: ArchiveStore) -> int:
    ok = True
    for ref in kline_refs() + funding_refs():
        store.fetch(ref)
        if ref.dataset is Dataset.KLINES:
            report = check_completeness(store.load_klines([ref]), s9.INTERVAL_MS, ref.start_ms, ref.end_ms)
            if report.missing or report.duplicates or report.out_of_order:
                print(f"{ref.filename}: {report.present}/{report.expected}, missing {report.missing}, "
                      f"duplicates {report.duplicates}, out of order {report.out_of_order}")
            ok = ok and report.duplicates == 0 and report.out_of_order == 0
    print(f"klines hash {store.dataset_hash(kline_refs())}, funding hash {store.dataset_hash(funding_refs())}")
    return 0 if ok else 1


def year_of(ms: int) -> int:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).year


def count(store: ArchiveStore, out_dir: Path) -> int:
    bars = [b for b in store.load_klines(kline_refs()) if b.open_time < HOLDOUT_START_MS]
    payload: dict = {"study": "S9", "commit": _commit(), "outcome_blind": True,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(kline_refs()), "bars": len(bars),
                     "gate": {"train": GATE_TRAIN, "validation": GATE_VALIDATION, "holdout": GATE_HOLDOUT,
                              "holdout_months": HOLDOUT_MONTHS}, "variants": {}}
    sections = {"train": (SIGNALS_MS, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}
    for variant in s9.S9_VARIANTS:
        row: dict = {"params": variant.params}
        for name, (lo, hi) in sections.items():
            result = s9.count_signals(bars, variant, lo, hi)
            c = result.counts
            row[name] = {"upper": result.upper, "lower": result.lower, "choch": c.choch, "zone_rejected": c.zone_rejected,
                         "expired": c.expired, "invalidated": c.invalidated, "replaced": c.replaced,
                         "rr_rejected": c.rr_rejected, "resets": c.resets}
        by_year: dict[int, int] = {}
        whole = s9.Detector(variant)
        for bar in bars:
            if whole.step(bar) is not None and bar.open_time >= SIGNALS_MS:
                by_year[year_of(bar.open_time)] = by_year.get(year_of(bar.open_time), 0) + 1
        weakest = min(range(2020, 2025), key=lambda y: (by_year.get(y, 0), y))
        projected = by_year.get(weakest, 0) / 12 * HOLDOUT_MONTHS
        row["by_year_upper"] = {str(y): by_year.get(y, 0) for y in range(2020, 2025)}
        row["projected_holdout"] = round(projected, 1)
        row["weakest_year"] = weakest
        row["passes_gate"] = (row["train"]["lower"] >= GATE_TRAIN and row["validation"]["lower"] >= GATE_VALIDATION
                              and projected >= GATE_HOLDOUT)
        payload["variants"][variant.variant_id] = row
        print(f"{variant.variant_id:9s} train {row['train']['lower']:5d}/{row['train']['upper']:5d}  "
              f"validation {row['validation']['lower']:5d}/{row['validation']['upper']:5d}  "
              f"holdout~{projected:6.1f} ({weakest})  CHoCH T {row['train']['choch']}  R:R<2 T {row['train']['rr_rejected']}  "
              f"{'PASS' if row['passes_gate'] else 'below gate'}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s9_count_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s9_count_{stamp}.md").write_text(count_markdown(payload))
    print(f"written {path}")
    return 0


def count_markdown(p: dict) -> str:
    g = p["gate"]
    lines = ["# S9 Zähllauf (Machbarkeits-Gate, ergebnisblind)", "",
             f"Commit `{p['commit']}`, Datensatz-Hash `{p['dataset_hash']}`, {p['bars']} 15m-Kerzen BTCUSDT bis 2024-12, "
             f"erstellt {p['created']}. Gate: Training ≥ {g['train']}, Validierung ≥ {g['validation']} Signale (untere Zahl: "
             f"jeder Trade läuft bis zum Zeitstop), hochgerechneter Holdout ≥ {g['holdout']} (schwächstes Jahr × "
             f"{g['holdout_months']} Monate). Keine Ausstiege, kein R.", "",
             "| Variante | Training untere/obere | Validierung untere/obere | Holdout hochgerechnet (Jahr) | Gate |",
             "|---|---:|---:|---:|---|"]
    for vid, v in p["variants"].items():
        t, val = v["train"], v["validation"]
        lines.append(f"| {vid} | {t['lower']} / {t['upper']} | {val['lower']} / {val['upper']} | {v['projected_holdout']} "
                     f"({v['weakest_year']}) | {'BESTANDEN' if v['passes_gate'] else 'nicht bestanden'} |")
    lines += ["", "## Wo die Setups hängen bleiben (Training / Validierung)", "",
              "| Variante | CHoCH | Zone verfehlt | verfallen | Ursprung verletzt | ersetzt | R:R < 2 | Signale |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for vid, v in p["variants"].items():
        t, val = v["train"], v["validation"]
        lines.append(f"| {vid} | " + " | ".join(f"{t[k]} / {val[k]}" for k in
                                                ("choch", "zone_rejected", "expired", "invalidated", "replaced", "rr_rejected", "upper")) + " |")
    lines += ["", "Je Kalenderjahr (Signale): " + "; ".join(
        f"{vid} " + ", ".join(f"{y} {n}" for y, n in v["by_year_upper"].items()) for vid, v in p["variants"].items()) + ".",
        "", "Holdout 2025+ nicht geladen."]
    return "\n".join(lines) + "\n"


def newest_count(out_dir: Path) -> dict:
    reports = sorted(out_dir.glob("s9_count_*.json"))
    if not reports:
        raise SystemExit("no s9_count_*.json in --out; run `count` first")
    return json.loads(reports[-1].read_text())


def train(store: ArchiveStore, out_dir: Path, *, runs: int, all_variants: bool) -> int:
    gate = newest_count(out_dir)
    passed = {vid for vid, v in gate["variants"].items() if v["passes_gate"]}
    specs = [spec for spec in s9.specs() if all_variants or spec.variant_id in passed]
    if not specs:
        print("no variant passed the feasibility gate; nothing to evaluate")
        return 0
    config = RunConfig(random_runs=runs, seed=s9.SEED)

    results, candidates, context = run(store, specs=specs, config=config, progress=lambda line: print(line, flush=True))
    context["gate_report_commit"] = gate["commit"]
    context["all_variants"] = all_variants
    report = write_report(out_dir, results, candidates, context, config, len(specs), _commit())
    target = report.with_name(report.name.replace("r4_", "s9_train_"))
    text = report.read_text().split("\n", 1)[1]
    target.write_text(f"# Studie S9 – Training und Validierung (Lauf mit dem allgemeinen Runner)\n{text}")
    report.unlink()
    report.with_suffix(".json").rename(target.with_suffix(".json"))
    print(f"report: {target}")
    print(f"candidates: {', '.join(candidates) or 'none'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["fetch", "count", "train"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    parser.add_argument("--random-runs", type=int, default=10_000)
    parser.add_argument("--all-variants", action="store_true", help="evaluate variants below the gate too (stated in the report)")
    args = parser.parse_args(argv)
    store = ArchiveStore(args.root)
    if args.command == "fetch":
        return fetch(store)
    if args.command == "count":
        return count(store, args.out)
    return train(store, args.out, runs=args.random_runs, all_variants=args.all_variants)


if __name__ == "__main__":
    raise SystemExit(main())
