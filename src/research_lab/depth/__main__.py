"""Order book research CLI (no API key, no orders).

    python -m src.research_lab.depth record --root ~/TIM-research/depth [--seconds 600]
    python -m src.research_lab.depth replay --root ~/TIM-research/depth [--out result.json]
    python -m src.research_lab.depth tardis-check --day 2020-06-01 --dir ~/TIM-research/tardis [--out result.json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import signal
from datetime import date
from pathlib import Path

from src.research_lab.depth import recorder, replay, tardis


def _emit(obj: dict, out: Path | None) -> None:
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    if out is not None:
        out.write_text(text + "\n")
    print(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m src.research_lab.depth")
    sub = p.add_subparsers(dest="cmd", required=True)
    rc = sub.add_parser("record")
    rc.add_argument("--root", type=Path, required=True)
    rc.add_argument("--seconds", type=float)
    rp = sub.add_parser("replay")
    rp.add_argument("--root", type=Path, required=True)
    rp.add_argument("--out", type=Path)
    tc = sub.add_parser("tardis-check")
    tc.add_argument("--day", type=date.fromisoformat, required=True)
    tc.add_argument("--dir", type=Path, required=True)
    tc.add_argument("--out", type=Path)
    tc.add_argument("--tick", default="0.1", help="instrument tick on that day (0.01 in 2020)")
    a = p.parse_args(argv)
    if a.cmd == "record":
        def _term(*_):  # launchd/systemd send SIGTERM: stop like Ctrl-C so every segment is closed cleanly
            raise KeyboardInterrupt

        signal.signal(signal.SIGTERM, _term)
        try:
            counts = asyncio.run(recorder.record(a.root.expanduser(), stop_after=a.seconds))
        except recorder.StorageError as exc:
            print(json.dumps({"state": "failed", "error": str(exc)}), flush=True)
            return 2
        except KeyboardInterrupt:
            print(json.dumps({"state": "stopped by signal"}), flush=True)
            return 0
        print(json.dumps(counts))
        return 0
    if a.cmd == "replay":
        res = replay.replay(a.root.expanduser())
        _emit(res.as_dict(), a.out)
        return 0 if res.as_dict()["ok"] else 1
    folder = a.dir.expanduser()
    book = tardis.download("incremental_book_L2", a.day, folder)
    trades = tardis.download("trades", a.day, folder)
    _emit(tardis.check(book, trades, a.day, tick=a.tick).as_dict(), a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
