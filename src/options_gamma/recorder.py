"""Raw Deribit options recorder (public API, no key, no account, read-only).

Deribit keeps no history of its options book. The level log of the runtime
(``gamma_data.append_level_log``) stores only the computed levels. This recorder
stores the raw book summary plus index price, so later studies can recompute
walls, flip and regime with any rule version.

    python -m src.options_gamma.recorder once  [--data-dir DIR]
    python -m src.options_gamma.recorder run   [--data-dir DIR] [--interval 3600]

One gzip JSON-lines file per UTC day, one line per snapshot. ``--data-dir`` defaults
to ``$TIM_OPTIONS_DATA_DIR`` or ``~/Library/Application Support/TIM/research-lab/options/raw``.
Observation only: nothing here trades or changes a score.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.dashboard.gamma_data import _fetch_json, _result

log = logging.getLogger("options-recorder")
DEFAULT_INTERVAL = 3600
CURRENCIES = ("BTC",)
Fetch = Callable[[str, Mapping[str, str]], Any]


def default_dir() -> Path:
    env = os.environ.get("TIM_OPTIONS_DATA_DIR")
    return Path(env) if env else Path.home() / "Library/Application Support/TIM/research-lab/options/raw"


def capture(currency: str = "BTC", fetch: Fetch | None = None, now: datetime | None = None) -> dict[str, Any]:
    """One raw snapshot: all option book-summary rows and the index price, unchanged."""
    fetch = fetch or _fetch_json
    rows = _result(fetch("get_book_summary_by_currency", {"currency": currency, "kind": "option"}), "book summary")
    if not isinstance(rows, list) or not rows:
        raise ValueError("deribit book summary: empty or not a list")
    index = _result(fetch("get_index_price", {"index_name": f"{currency.lower()}_usd"}), "index price")
    spot = index.get("index_price") if isinstance(index, Mapping) else None
    if not isinstance(spot, (int, float)) or isinstance(spot, bool) or spot <= 0:
        raise ValueError("deribit index price missing")
    moment = now or datetime.now(timezone.utc)
    return {"source": "DERIBIT_PUBLIC_OPTIONS_BOOK_SUMMARY", "currency": currency, "as_of": moment.isoformat(),
            "index_price": float(spot), "rows": rows}


def append(snapshot: Mapping[str, Any], data_dir: Path) -> Path:
    """Append one snapshot to the file of its UTC day (a gzip member per line, so a cut-off write loses one line)."""
    day = datetime.fromisoformat(str(snapshot["as_of"])).astimezone(timezone.utc).strftime("%Y-%m-%d")
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / f"{snapshot['currency'].lower()}_options_{day}.jsonl.gz"
    line = (json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    with path.open("ab") as handle:
        handle.write(gzip.compress(line))
    return path


def read(path: Path) -> list[dict[str, Any]]:
    """All snapshots of one day file."""
    with gzip.open(path, "rb") as handle:
        return [json.loads(line) for line in handle.read().decode("utf-8").splitlines() if line.strip()]


def record_once(data_dir: Path, fetch: Fetch | None = None, now: datetime | None = None) -> list[Path]:
    paths = []
    for currency in CURRENCIES:
        paths.append(append(capture(currency, fetch=fetch, now=now), data_dir))
    return paths


def run(data_dir: Path, interval: int, stop: threading.Event, fetch: Fetch | None = None) -> None:
    while not stop.is_set():
        try:
            for path in record_once(data_dir, fetch=fetch):
                log.info("saved snapshot to %s", path.name)
        except Exception as error:  # noqa: BLE001 - one failed read must not end the service
            log.warning("options snapshot failed: %s: %s", type(error).__name__, error)
        stop.wait(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.options_gamma.recorder")
    parser.add_argument("command", choices=("once", "run"))
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    data_dir = args.data_dir or default_dir()
    if args.command == "once":
        for path in record_once(data_dir):
            print(path)
        return 0
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run(data_dir, max(60, args.interval), stop)
    return 0


if __name__ == "__main__":
    sys.exit(main())
