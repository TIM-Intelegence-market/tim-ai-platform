"""Order-book recorder CLI (public feeds, no API key, no orders).

    python -m src.research_lab.orderbook record --root ~/Documents/TIM/orderbook/binance [--symbols BTCUSDT] [--seconds 600]
    python -m src.research_lab.orderbook check --root ~/Documents/TIM/orderbook/binance --symbol BTCUSDT [--day 2026-11-17]
    python -m src.research_lab.orderbook audit --root ~/Documents/TIM/orderbook/binance --symbol BTCUSDT [--start ISO] [--end ISO]
        [--window-hours 72] [--pause-seconds 10] [--open-grace-seconds 120] [--out FILE]   (read-only, streaming)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
from pathlib import Path

from src.research_lab.bitunix.recorder import StorageError, validate_symbols
from src.research_lab.orderbook import audit, binance, book


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
    au = sub.add_parser("audit", help="read-only streaming integrity audit (time coverage, update-id chain, segments)")
    au.add_argument("--root", type=Path, required=True)
    au.add_argument("--symbol", default="BTCUSDT")
    au.add_argument("--start", help="ISO 8601, UTC if no offset; default first depth event")
    au.add_argument("--end", help="ISO 8601, UTC if no offset; default last depth event")
    au.add_argument("--window-hours", type=float, default=audit.ACCEPT_WINDOW_HOURS)
    au.add_argument("--pause-seconds", type=float, default=audit.DEFAULT_PAUSE_SECONDS)
    au.add_argument("--open-grace-seconds", type=float, default=audit.DEFAULT_OPEN_GRACE_SECONDS)
    au.add_argument("--out", type=Path, help="also write the report here (must be outside --root)")
    a = p.parse_args(argv)
    if a.cmd == "audit":
        (symbol,) = validate_symbols([a.symbol])
        root = a.root.expanduser().resolve()
        if a.out is not None and a.out.expanduser().resolve().is_relative_to(root):
            print(json.dumps({"state": "refused", "error": "--out must be outside --root (the archive is read-only)"}))
            return 2
        try:
            start_ms, end_ms = audit.parse_time(a.start), audit.parse_time(a.end)
        except ValueError as exc:
            print(json.dumps({"state": "refused", "error": f"bad time: {exc}"}))
            return 2
        report = audit.audit(root, symbol, start_ms=start_ms, end_ms=end_ms, window_hours=a.window_hours,
                             pause_seconds=a.pause_seconds, open_grace_seconds=a.open_grace_seconds)
        text = json.dumps(report, indent=1)
        if a.out is not None:
            a.out.expanduser().write_text(text + "\n")
        print(text)
        return 0
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
