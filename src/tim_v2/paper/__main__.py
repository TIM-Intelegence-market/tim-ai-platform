"""CLI: ``python -m src.tim_v2.paper replay|isolation``. Paper only; there is no live mode."""
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from .adapter import AdapterConfig
from .isolation import scan
from .kill_switch import KillSwitch
from .runner import bar_from_row, read_jsonl, replay, write_outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.tim_v2.paper", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    rp = sub.add_parser("replay", help="replay bars and order instructions through the fake adapter")
    rp.add_argument("--bars", type=Path, required=True)
    rp.add_argument("--orders", type=Path, required=True)
    rp.add_argument("--out", type=Path, required=True)
    rp.add_argument("--equity", default="1000")
    sub.add_parser("isolation", help="print the static isolation proof; exit 1 on any violation")
    args = parser.parse_args(argv)

    if args.cmd == "isolation":
        report = scan()
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.ok else 1

    isolation = scan()
    if not isolation.ok:
        print(json.dumps(isolation.to_dict(), indent=2), file=sys.stderr)
        return 1
    bars = [bar_from_row(r) for r in read_jsonl(args.bars)]
    result = replay(bars, read_jsonl(args.orders), AdapterConfig(initial_equity=Decimal(args.equity)),
                    KillSwitch.from_env())
    summary = write_outputs(result, args.out)
    print(json.dumps({k: summary[k] for k in ("final_equity", "reconciliation_failures", "kill_switch")},
                     indent=2, default=str))
    return 0 if result.reconciliation_failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
