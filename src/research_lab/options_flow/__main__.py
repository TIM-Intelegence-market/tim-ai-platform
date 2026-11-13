"""CLI: ``record`` (Dauerdienst, read-only) and ``audit`` (Datenqualität der Aufzeichnung)."""
from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path

from src.research_lab.bitunix.recorder import StorageError
from src.research_lab.options_flow import contract, recorder


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="options_flow", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="record public Deribit option trades, book summary and DVOL")
    rec.add_argument("--root", type=Path, required=True)
    rec.add_argument("--currency", default="BTC", choices=recorder.CURRENCIES)
    rec.add_argument("--seconds", type=float, default=None, help="stop after N seconds (tests)")
    aud = sub.add_parser("audit", help="count trades, duplicates, rejects, gaps, latency of a recording")
    aud.add_argument("--root", type=Path, required=True)
    aud.add_argument("--currency", default="BTC", choices=recorder.CURRENCIES)
    a = p.parse_args(argv)
    if a.cmd == "audit":
        print(json.dumps(contract.audit(a.root.expanduser(), a.currency), indent=1))
        return 0

    def _term(*_):  # launchd/kill send SIGTERM: stop like Ctrl-C so every segment is closed cleanly
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _term)
    try:
        counts = recorder.record(a.root.expanduser(), a.currency, stop_after=a.seconds)
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
