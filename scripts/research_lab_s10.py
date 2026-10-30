"""Study S10: fetch USD-M 1m/5m archives (BTC/ETH/SOL), then the outcome-blind feasibility count.

    python scripts/research_lab_s10.py fetch                 # 1m + 5m klines and funding, 2020 .. 2024-12
    python scripts/research_lab_s10.py count --out DIR       # signal counts only, no exits, no R

Needs network access to data.binance.vision for `fetch` (run on the Mac). Holdout months
(2025+) are refused by the store and never requested here. Training and validation runs
come only after the gate and Uzi's decision (preregistration section 8).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.archive import ArchiveRef, Dataset, Market
from src.research_lab.data.parse import Kline, check_completeness
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months
from src.research_lab.hypotheses import s10
from src.research_lab.protocol import (
    HOLDOUT_START_MS,
    MIN_TRADES_HOLDOUT,
    MIN_TRADES_TRAIN,
    UNIVERSE_LIMITATION,
    VALIDATION_START_MS,
    _utc_ms,
)

LAST = (2024, 12)
SYMBOLS = {"BTCUSDT": (2020, 1), "ETHUSDT": (2020, 1), "SOLUSDT": (2020, 9)}  # first full USD-M month (as S7)
GATE_TRAIN = MIN_TRADES_TRAIN["short"]  # 500
GATE_VALIDATION = MIN_TRADES_TRAIN["short"] // 2  # 250
GATE_HOLDOUT = MIN_TRADES_HOLDOUT["short"]  # 200
GATE_DAYS = {"train": 160, "validation": 183}  # distinct signal days (protocol 1.3 A3 numbers, outcome-blind bound)
HOLDOUT_MONTHS = 21  # 2025-01 .. 2026-09
YEARS = range(2020, 2025)


def refs(symbol: str, dataset: Dataset, interval: str | None = None) -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, dataset, y, m, interval, symbol) for y, m in months(SYMBOLS[symbol], LAST)]


def all_refs() -> list[ArchiveRef]:
    return [r for symbol in SYMBOLS for r in refs(symbol, Dataset.KLINES, "1m") + refs(symbol, Dataset.KLINES, "5m")
            + refs(symbol, Dataset.FUNDING)]


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def fetch(store: ArchiveStore) -> int:
    ok = True
    for ref in all_refs():
        store.fetch(ref)
        if ref.dataset is Dataset.KLINES:
            step = 60_000 if ref.interval == "1m" else s10.INTERVAL_MS
            report = check_completeness(store.load_klines([ref]), step, ref.start_ms, ref.end_ms)
            if report.missing or report.duplicates or report.out_of_order:
                print(f"{ref.filename}: {report.present}/{report.expected}, missing {report.missing}, "
                      f"duplicates {report.duplicates}, out of order {report.out_of_order}", flush=True)
            ok = ok and report.duplicates == 0 and report.out_of_order == 0
    kl = [r for r in all_refs() if r.dataset is Dataset.KLINES]
    print(f"klines hash {store.dataset_hash(kl)}")
    return 0 if ok else 1


def _stream(store: ArchiveStore, symbol: str) -> Iterator[Kline]:
    for ref in refs(symbol, Dataset.KLINES, "1m"):  # one month at a time keeps memory small
        yield from store.load_klines([ref])


def count(store: ArchiveStore, out_dir: Path) -> int:
    kl = [r for r in all_refs() if r.dataset is Dataset.KLINES]
    payload: dict = {"study": "S10", "commit": _commit(), "outcome_blind": True,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "dataset_hash": store.dataset_hash(kl),
                     "gate": {"train": GATE_TRAIN, "validation": GATE_VALIDATION, "holdout": GATE_HOLDOUT,
                              "holdout_months": HOLDOUT_MONTHS, "days": GATE_DAYS},
                     "symbols": {}, "variants": {}}
    signals: dict[str, list[tuple[str, s10.DaySignal]]] = {v.variant_id: [] for v in s10.S10_VARIANTS}
    counts: dict[str, dict[str, dict[str, int]]] = {v.variant_id: {} for v in s10.S10_VARIANTS}
    for symbol, first in SYMBOLS.items():
        start = _utc_ms(*first, 1)
        bars_5m = store.load_klines(refs(symbol, Dataset.KLINES, "5m"))
        days = s10.trading_days(start, HOLDOUT_START_MS)
        data = s10.split_day_data(days, _stream(store, symbol), bars_5m)
        daily = s10.daily_bars(bars_5m)
        payload["symbols"][symbol] = {"first_month": f"{first[0]}-{first[1]:02d}", "trading_days": len(days),
                                      "bars_5m": len(bars_5m)}
        del bars_5m
        for variant in s10.S10_VARIANTS:
            result = s10.count_signals(days, data, daily, variant)
            signals[variant.variant_id] += [(symbol, sig) for sig in result.signals]
            counts[variant.variant_id][symbol] = {k: getattr(result.counts, k) for k in result.counts.__dataclass_fields__}
            print(f"{symbol} {variant.variant_id}: {result.counts}", flush=True)
    for variant in s10.S10_VARIANTS:
        rows = signals[variant.variant_id]
        row: dict = {"params": variant.params, "funnel": counts[variant.variant_id]}
        for name, (lo, hi) in {"train": (0, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}.items():
            part = [(s, x) for s, x in rows if lo <= x.signal_time < hi]
            row[name] = {"signals": len(part), "signal_days": len({x.day for _, x in part}),
                         "btc": sum(1 for s, _ in part if s == "BTCUSDT"),
                         "long": sum(1 for _, x in part if x.direction > 0), "short": sum(1 for _, x in part if x.direction < 0)}
        by_year = {y: sum(1 for _, x in rows if x.day.year == y) for y in YEARS}
        weakest = min(YEARS, key=lambda y: (by_year[y], y))
        projected = by_year[weakest] / 12 * HOLDOUT_MONTHS
        row["by_year"] = {str(y): n for y, n in by_year.items()}
        row["weakest_year"] = weakest
        row["projected_holdout"] = round(projected, 1)
        row["passes_gate"] = (row["train"]["signals"] >= GATE_TRAIN and row["validation"]["signals"] >= GATE_VALIDATION
                              and projected >= GATE_HOLDOUT and row["train"]["signal_days"] >= GATE_DAYS["train"]
                              and row["validation"]["signal_days"] >= GATE_DAYS["validation"])
        payload["variants"][variant.variant_id] = row
        print(f"{variant.variant_id}: train {row['train']['signals']} ({row['train']['signal_days']} days), validation "
              f"{row['validation']['signals']} ({row['validation']['signal_days']} days), holdout~{projected:.1f} "
              f"({weakest}) {'PASS' if row['passes_gate'] else 'below gate'}", flush=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s10_count_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    (out_dir / f"s10_count_{stamp}.md").write_text(count_markdown(payload))
    print(f"written {path}")
    return 0


FUNNEL = (("days", "Handelstage"), ("data_missing", "Daten fehlen"), ("atr_missing", "Tages-ATR fehlt"),
          ("ib_narrow", "IB zu eng"), ("no_breakout", "kein Ausbruch bis 12:00"), ("invalidated", "Schluss jenseits VA"),
          ("no_retest", "kein Retest bis 13:00"), ("no_reaction", "kein Reaktionsschluss"),
          ("no_absorption", "keine Absorption"), ("no_entry_bar", "keine Einstiegskerze"), ("signals", "Signale"))


def count_markdown(p: dict) -> str:
    g = p["gate"]
    lines = ["# S10 Zähllauf (Machbarkeits-Gate, ergebnisblind)", "",
             f"Commit `{p['commit']}`, Datensatz-Hash `{p['dataset_hash']}`, erstellt {p['created']}. "
             f"USD-M 1m (IB-Profil) und 5m, {', '.join(f'{s} ab {v['first_month']}' for s, v in p['symbols'].items())}, "
             f"bis 2024-12. Gate je Variante, gepoolt: Training ≥ {g['train']} und ≥ {g['days']['train']} Signaltage, "
             f"Validierung ≥ {g['validation']} und ≥ {g['days']['validation']} Signaltage, hochgerechneter Holdout ≥ "
             f"{g['holdout']} (schwächstes Jahr × {g['holdout_months']} Monate). Keine Ausstiege, kein R.", "",
             "| Variante | Training Signale (Tage, BTC) | Validierung Signale (Tage, BTC) | Holdout hochgerechnet (Jahr) | Gate |",
             "|---|---:|---:|---:|---|"]
    for vid, v in p["variants"].items():
        t, val = v["train"], v["validation"]
        lines.append(f"| {vid} | {t['signals']} ({t['signal_days']}, {t['btc']}) | {val['signals']} ({val['signal_days']}, "
                     f"{val['btc']}) | {v['projected_holdout']} ({v['weakest_year']}) | "
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
    parser.add_argument("command", choices=["fetch", "count"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    args = parser.parse_args(argv)
    store = ArchiveStore(args.root)
    if args.command == "fetch":
        return fetch(store)
    return count(store, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
