"""Order-book recorder CLI (public feeds, no API key, no orders).

    python -m src.research_lab.orderbook record --root ~/Documents/TIM/orderbook/binance [--symbols BTCUSDT] [--seconds 600]
    python -m src.research_lab.orderbook check --root ~/Documents/TIM/orderbook/binance --symbol BTCUSDT [--day 2026-11-17]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
from pathlib import Path

from src.research_lab.bitunix.recorder import StorageError, validate_symbols
from src.research_lab.orderbook import binance, book


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.research_lab.orderbook")
    sub = p.add_subparsers(dest="cmd", required=True)
    rc = sub.add_parser("record")
    rc.add_argument("--root", type=Path, required=True)
    rc.add_argument("--symbols", default="BTCUSDT")
    rc.add_argument("--seconds", type=float)
    rc.add_argument("--snapshot-limit", type=int, default=1000)
    rc.add_argument("--snapshot-every", type=float, default=binance.SNAPSHOT_EVERY)
    ck = sub.add_parser("check")
    ck.add_argument("--root", type=Path, required=True)
    ck.add_argument("--symbol", default="BTCUSDT")
    ck.add_argument("--day", help="YYYY-MM-DD, default all days")
    a = p.parse_args(argv)
    if a.cmd == "check":
        (symbol,) = validate_symbols([a.symbol])
        pattern = f"{a.day}.*.jsonl.gz" if a.day else "*.jsonl.gz"
        print(json.dumps(book.check((a.root.expanduser() / symbol).glob(pattern)), indent=1))
        return 0

    def _term(*_):  # launchd/kill send SIGTERM: stop like Ctrl-C so every segment is closed cleanly
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _term)
    try:
        counts = asyncio.run(binance.record(a.root.expanduser(), a.symbols.split(","), stop_after=a.seconds,
                                            snapshot_limit=a.snapshot_limit, snapshot_every=a.snapshot_every))
    except StorageError as exc:
        print(json.dumps({"state": "failed", "error": str(exc)}), flush=True)
        return 2
    except KeyboardInterrupt:
        print(json.dumps({"state": "stopped by signal"}), flush=True)
        return 0
    print(json.dumps(counts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
