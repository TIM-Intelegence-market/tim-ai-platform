"""Study S14: outcome-blind feasibility count of pairs trading ETH/BTC, SOL/BTC, SOL/ETH (1h from 5m).

    python scripts/research_lab_s14.py count --out DIR    # entry signals per variant, no exits, no R

Uses the 5m USD-M klines already fetched for S10 (`scripts/research_lab_s10.py fetch`, run on the
Mac). Holdout months (2025+) are refused by the store and never requested here; S14 is proposed as
its own family and never loads them. Counted are all crossings of |z| = 2 (section 5.1), ignoring
open positions, so the numbers are an upper bound of the trades.
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
from src.research_lab.hypotheses import s14
from src.research_lab.protocol import (
    HOLDOUT_START_MS,
    MIN_TRADES_TRAIN,
    UNIVERSE_LIMITATION,
    VALIDATION_START_MS,
)

LAST = (2024, 12)
SYMBOLS = {"BTCUSDT": (2020, 1), "ETHUSDT": (2020, 1), "SOLUSDT": (2020, 9)}  # first full USD-M month (as S7/S10)
PAIRS = (("ETHUSDT", "BTCUSDT"), ("SOLUSDT", "BTCUSDT"), ("SOLUSDT", "ETHUSDT"))  # (y, x)
GATE_TRAIN = MIN_TRADES_TRAIN["short"]  # 500
GATE_VALIDATION = MIN_TRADES_TRAIN["short"] // 2  # 250
GATE_DAYS = {"train": 160, "validation": 183}
SECTIONS = {"train": (0, VALIDATION_START_MS), "validation": (VALIDATION_START_MS, HOLDOUT_START_MS)}
YEARS = range(2020, 2025)


def refs(symbol: str) -> list[ArchiveRef]:
    return [ArchiveRef(Market.USDM, Dataset.KLINES, y, m, "5m", symbol) for y, m in months(SYMBOLS[symbol], LAST)]


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["count"])
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out", type=Path, default=Path("docs/research_lab/reports"))
    args = parser.parse_args(argv)
    return count(ArchiveStore(args.root), args.out)


if __name__ == "__main__":
    raise SystemExit(main())
