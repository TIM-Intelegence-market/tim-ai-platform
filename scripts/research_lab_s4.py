"""Study S4: fetch the archives and run the outcome-blind feasibility count (section 6.1).

    python scripts/research_lab_s4.py fetch            # USD-M 1h + 1d + funding, BTC/ETH/SOL, up to 2024-12
    python scripts/research_lab_s4.py count --out DIR  # signal counts only, no exits, no R, no hit rate

Needs network access to data.binance.vision for `fetch` (run on the Mac). Holdout
months (2025+) are refused by the store. `count` writes s4_count_<stamp>.json with
commit, dataset hashes and per-variant counts; it never computes an outcome.
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

from src.research_lab.data.archive import ArchiveRef, Dataset, Market  # noqa: E402
from src.research_lab.data.parse import check_completeness  # noqa: E402
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months  # noqa: E402
from src.research_lab.hypotheses import s4  # noqa: E402
from src.research_lab.protocol import HOLDOUT_START_MS, _utc_ms  # noqa: E402

LAST_MONTH = (2024, 12)
# First archive month (warm-up) and first counted month per instrument, section 3 (checked 2026-10-25).
SYMBOLS = {"BTCUSDT": ((2020, 1), (2020, 1)), "ETHUSDT": ((2020, 1), (2020, 1)), "SOLUSDT": ((2020, 9), (2020, 10))}
TRAIN_END = _utc_ms(2023, 1, 1)
HOLDOUT_COIN_MONTHS = 3 * 21
GATE = 1_700


def refs(symbol: str, dataset: Dataset, interval: str | None) -> list[ArchiveRef]:
    first, _ = SYMBOLS[symbol]
    return [ArchiveRef(Market.USDM, dataset, y, m, interval, symbol=symbol) for y, m in months(first, LAST_MONTH)]


def all_refs() -> list[ArchiveRef]:
    out: list[ArchiveRef] = []
    for symbol in SYMBOLS:
        out += refs(symbol, Dataset.KLINES, "1h") + refs(symbol, Dataset.KLINES, "1d") + refs(symbol, Dataset.FUNDING, None)
    return out


def fetch(store: ArchiveStore) -> int:
    ok = True
    for ref in all_refs():
        store.fetch(ref)
        if ref.dataset is Dataset.KLINES:
            report = check_completeness(store.load_klines([ref]), 3_600_000 if ref.interval == "1h" else 86_400_000,
                                        ref.start_ms, ref.end_ms)
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


def count(store: ArchiveStore, out_dir: Path) -> int:
    payload: dict = {"study": "S4", "protocol": "S4 1.0", "commit": _commit(), "gate_trades": GATE,
                     "holdout_coin_months": HOLDOUT_COIN_MONTHS, "outcome_blind": True,
                     "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dataset_hashes": {},
                     "coin_months": {}, "variants": {}}
    data = {}
    for symbol, (_, start) in SYMBOLS.items():
        hourly_refs, daily_refs = refs(symbol, Dataset.KLINES, "1h"), refs(symbol, Dataset.KLINES, "1d")
        hourly = [b for b in store.load_klines(hourly_refs) if b.open_time < HOLDOUT_START_MS]
        daily = [b for b in store.load_klines(daily_refs) if b.open_time < HOLDOUT_START_MS]
        payload["dataset_hashes"][symbol] = store.dataset_hash(hourly_refs + daily_refs)
        begin = _utc_ms(start[0], start[1], 1)
        data[symbol] = (hourly, daily, begin)
        payload["coin_months"][symbol] = {"train": len(months(start, (2022, 12))), "validation": 24}
    total_coin_months = sum(v["train"] + v["validation"] for v in payload["coin_months"].values())
    for variant in s4.S4_VARIANTS:
        rows = {}
        lower_total = 0
        for symbol, (hourly, daily, begin) in data.items():
            for section, (lo, hi) in {"train": (begin, TRAIN_END), "validation": (TRAIN_END, HOLDOUT_START_MS)}.items():
                result = s4.count_signals(hourly, variant, daily, lo, hi)
                rows[f"{symbol}/{section}"] = dataclasses.asdict(result)
                lower_total += result.lower
        projected = lower_total / total_coin_months * HOLDOUT_COIN_MONTHS
        payload["variants"][variant.variant_id] = {"hypothesis": variant.hypothesis, "counts": rows,
                                                   "lower_total": lower_total, "projected_holdout_lower": round(projected, 1),
                                                   "passes_gate": projected >= GATE}
        print(f"{variant.variant_id:16s} lower {lower_total:6d}  projected holdout {projected:7.1f}  "
              f"{'PASS' if projected >= GATE else 'below gate'}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    path = out_dir / f"s4_count_{stamp}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    print(f"written {path}")
    return 0


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
