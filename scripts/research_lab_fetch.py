"""Fetch and verify Binance archive months for the research lab (R1).

Example (one probe month):
    python scripts/research_lab_fetch.py --market usdm --interval 1h --from 2024-01 --to 2024-01

Needs network access to data.binance.vision. Holdout months (2025+) are refused.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_lab.data.archive import INTERVAL_MS, ArchiveRef, Dataset, Market  # noqa: E402
from src.research_lab.data.parse import check_completeness  # noqa: E402
from src.research_lab.data.store import DEFAULT_ROOT, ArchiveStore, months  # noqa: E402

MARKETS = {"spot": Market.SPOT, "usdm": Market.USDM}


def _month(value: str) -> tuple[int, int]:
    year, month = value.split("-")
    return int(year), int(month)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preset", choices=["r4"], help="fetch every archive the R4 run needs (up to 2024-12)")
    parser.add_argument("--market", choices=sorted(MARKETS))
    parser.add_argument("--interval", choices=sorted(INTERVAL_MS))
    parser.add_argument("--funding", action="store_true", help="fetch funding rates instead of klines")
    parser.add_argument("--from", dest="start", type=_month)
    parser.add_argument("--to", dest="end", type=_month)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    args = parser.parse_args(argv)
    store = ArchiveStore(args.root)
    if args.preset:
        from src.research_lab.runner import all_refs

        refs = all_refs()
    else:
        if not (args.market and args.start and args.end) or args.funding == bool(args.interval):
            parser.error("give --preset r4, or --market, --from, --to and either --interval or --funding")
        refs = [
            ArchiveRef(MARKETS[args.market], Dataset.FUNDING if args.funding else Dataset.KLINES, year, month, args.interval)
            for year, month in months(args.start, args.end)
        ]
    ok = True
    for ref in refs:
        store.fetch(ref)
        print(f"{ref.filename}: checksum PASS")
        if ref.dataset is Dataset.KLINES:
            report = check_completeness(store.load_klines([ref]), INTERVAL_MS[ref.interval], ref.start_ms, ref.end_ms)
            print(f"  candles {report.present}/{report.expected}, missing {report.missing}, duplicates {report.duplicates}, out of order {report.out_of_order}")
            for gap in report.gaps:
                print(f"  gap after {gap.after_open_time}: {gap.missing} missing")
            ok = ok and report.duplicates == 0 and report.out_of_order == 0
    print(f"dataset hash: {store.dataset_hash(refs)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
