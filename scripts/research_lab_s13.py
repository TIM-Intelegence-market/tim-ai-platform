"""Study S13: outcome-blind feasibility count of the noise-band breakout (BTC/ETH/SOL, 1m).

    python scripts/research_lab_s13.py count --out DIR    # first signal per session, no exits, no R

Uses the 1m USD-M archives already fetched for S10 (`scripts/research_lab_s10.py fetch`, run on
the Mac). Holdout months (2025+) are refused by the store and never requested here. Exits, R and
the random comparison come only after the gate and Uzi's decision (preregistration section 8).
One instrument at a time is held in memory (about 2.6 million 1m bars).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months
from src.research_lab.hypotheses import s13
from src.research_lab.protocol import (
    HOLDOUT_START_MS,
    MIN_TRADES_TRAIN,
    UNIVERSE_LIMITATION,
    VALIDATION_START_MS,
    _utc_ms,
)

LAST = (2024, 12)
SYMBOLS = {"BTCUSDT": (2020, 1), "ETHUSDT": (2020, 1), "SOLUSDT": (2020, 9)}  # first full USD-M month (as S7/S10)
GATE_TRAIN = MIN_TRADES_TRAIN["short"]  # 500
GATE_VALIDATION = MIN_TRADES_TRAIN["short"] // 2  # 250
GATE_DAYS = {"train": 160, "validation": 183}  # distinct signal days (protocol 1.3 A3 numbers)
YEARS = range(2020, 2025)


def refs(symbol: str) -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, "1m", symbol) for y, m in months(SYMBOLS[symbol], LAST)]


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["count"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    args = parser.parse_args(argv)
    return count(ArchiveStore(args.root), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
