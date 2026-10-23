#!/usr/bin/env python3
"""Startet das Team: Scanner -> Buzz-Tracker -> Papier-Bot. Einmal oder in Schleife (Standard alle 5 min).

Fällt eine Stufe aus, laufen die anderen weiter; der Fehler steht in stderr.
"""

from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import buzz  # noqa: E402
import paper_bot  # noqa: E402
import scanner  # noqa: E402
from common import BinancePublic, SnapshotMarket, default_data_dir, iso, utc_now  # noqa: E402


def cycle(market, buzz_sources, data_dir: Path, cfg: paper_bot.Config, top_n: int, log=print) -> None:
    log(f"--- Lauf {iso(utc_now())} ---")
    for name, fn in (
        ("Scanner", lambda: scanner.scan(market, data_dir, top_n=top_n, log=log)),
        ("Buzz", lambda: buzz.run(buzz_sources, data_dir, log=log)),
        ("Papier-Bot", lambda: paper_bot.run(market, data_dir, cfg=cfg, log=log)),
    ):
        try:
            fn()
        except Exception:
            log(f"{name} fehlgeschlagen:\n{traceback.format_exc()}", file=sys.stderr)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", type=Path, default=default_data_dir())
    p.add_argument("--loop", action="store_true", help="dauerhaft laufen")
    p.add_argument("--interval", type=int, default=300, help="Sekunden zwischen Läufen (min. 60)")
    p.add_argument("--top", type=int, default=100)
    p.add_argument("--market-snapshot", type=Path)
    p.add_argument("--buzz-snapshot", type=Path)
    a = p.parse_args(argv)
    market = SnapshotMarket.from_file(a.market_snapshot) if a.market_snapshot else BinancePublic()
    sources = buzz.SnapshotBuzzSources.from_file(a.buzz_snapshot) if a.buzz_snapshot else buzz.LiveBuzzSources()
    cfg = paper_bot.Config()
    while True:
        cycle(market, sources, a.data_dir, cfg, a.top)
        sys.stdout.flush()
        if not a.loop:
            return 0
        time.sleep(max(60, a.interval))


if __name__ == "__main__":
    raise SystemExit(main())
