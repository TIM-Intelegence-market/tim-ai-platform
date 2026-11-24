#!/usr/bin/env python3
"""Signalgruppe calls on paper: market check per call, paper diary per author. No orders, nothing is posted.

Subcommands:
  fetch  Download Bitunix contracts and bars (public API, no key) for the coins the calls name and write a
         snapshot file. Needs internet, so run it on the Mac; the cloud sandbox cannot reach Bitunix.
  run    Read the feed, check every call against the snapshot, update the diary and write the report.

Example:
  python3 scripts/signalgruppe_paper_diary.py cycle --feed-dir FEED --workdir WORKDIR   (fetch + run, used by the schedule)
  python3 scripts/signalgruppe_paper_diary.py fetch --feed-dir /mnt/project-files/signalgruppe --out snapshot.json
  python3 scripts/signalgruppe_paper_diary.py run --feed-dir /mnt/project-files/signalgruppe --snapshot snapshot.json \
      --diary diary.json --report papier-tagebuch.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.signalgruppe_channels import PROFILES, read_calls, source_names_hint  # noqa: E402
from src.knowledge.signalgruppe_feed import SignalgruppeFeedStore  # noqa: E402
from src.knowledge.signalgruppe_market_check import (  # noqa: E402
    DiaryEntry,
    MarketSnapshot,
    build_diary,
    merge_diary,
    render_diary_report,
)

BASE = "https://fapi.bitunix.com/api/v1/futures/market"
INTERVAL = "15m"
INTERVAL_MINUTES = 15
PAGE = 200  # bars per request


def _get(path: str, params: dict[str, object]) -> list[dict]:
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as response:  # noqa: S310 (fixed https host)
        payload = json.load(response)
    if payload.get("code") not in (0, "0"):
        raise RuntimeError(f"Bitunix {path}: {payload.get('msg')}")
    return payload.get("data") or []


def _fetch_bars(pair: str, start: datetime, end: datetime) -> list[dict]:
    """15m bars from ``start`` to ``end``, paged backwards from the end; deduplicated by time."""
    found: dict[str, dict] = {}
    cursor = int(end.timestamp() * 1000)
    start_ms = int(start.timestamp() * 1000)
    for _ in range(200):  # 200 pages of 200 bars cover about 400 days
        rows = _get("kline", {"symbol": pair, "interval": INTERVAL, "limit": PAGE, "endTime": cursor})
        if not rows:
            break
        for row in rows:
            found[str(row["time"])] = row
        oldest = min(int(row["time"]) for row in rows)
        if oldest <= start_ms or oldest >= cursor:
            break
        cursor = oldest - 1
        time.sleep(0.2)
    return sorted((row for row in found.values() if int(row["time"]) >= start_ms), key=lambda row: int(row["time"]))


def _calls(args: argparse.Namespace) -> dict:
    if hint := source_names_hint():
        print(hint, file=sys.stderr)
    return read_calls(SignalgruppeFeedStore(args.feed_dir).load())


def cmd_fetch(args: argparse.Namespace) -> int:
    now = datetime.now(timezone.utc)
    calls = _calls(args)
    wanted: dict[str, datetime] = {}  # pair -> earliest time we need (24 h before the first call is known)
    for items in calls.values():
        for tracked in items:
            # coin tips without levels are grade C but still get TIM's own analysis, so they need prices too
            graded = tracked.call.grade in ("A", "B") or PROFILES[tracked.profile].coin_calls
            if graded and tracked.symbol and tracked.bias in ("LONG", "SHORT"):
                pair = f"{tracked.symbol}USDT"
                need = min(tracked.call.message.posted_at, tracked.call.message.known_at) - timedelta(hours=25)
                wanted[pair] = min(need, wanted.get(pair, need))
    instruments = _get("trading_pairs", {})
    listed = {row["symbol"] for row in instruments}
    bars = {}
    for pair, start in sorted(wanted.items()):
        if pair not in listed:
            print(f"{pair}: nicht bei Bitunix gelistet, keine Kurse geholt")
            continue
        bars[pair] = _fetch_bars(pair, start, now)
        print(f"{pair}: {len(bars[pair])} Kerzen")
    snapshot = {"taken_at": now.isoformat(), "interval_minutes": INTERVAL_MINUTES,
                "instruments": [row for row in instruments if row["symbol"] in wanted], "bars": bars}
    Path(args.out).write_text(json.dumps(snapshot, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    snapshot = MarketSnapshot.load(args.snapshot)
    fresh = build_diary(_calls(args), snapshot)
    existing = []
    if args.diary.exists():
        existing = [DiaryEntry.from_dict(row) for row in json.loads(args.diary.read_text(encoding="utf-8"))["entries"]]
    entries = merge_diary(existing, fresh)
    args.diary.write_text(json.dumps({"updated_at": snapshot.taken_at.isoformat(), "entries": [item.to_dict() for item in entries]},
                                     ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = render_diary_report(entries, snapshot.taken_at)
    if args.report:
        Path(args.report).write_text(report, encoding="utf-8")
    entered = sum(1 for item in entries if item.entered)
    print(f"{len(entries)} Calls im Tagebuch, {entered} handelbar und mitgeführt, {len(entries) - entered} nicht handelbar")
    return 0


def cmd_cycle(args: argparse.Namespace) -> int:
    """fetch and run in one step, for a schedule: files live in --workdir (snapshot, diary, report)."""
    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    snapshot = workdir / "snapshot.json"
    status = cmd_fetch(argparse.Namespace(feed_dir=args.feed_dir, out=snapshot))
    if status:
        return status
    return cmd_run(argparse.Namespace(feed_dir=args.feed_dir, snapshot=snapshot, diary=workdir / "diary.json",
                                      report=workdir / "papier-tagebuch.md"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("fetch", cmd_fetch), ("run", cmd_run)):
        command = sub.add_parser(name)
        command.add_argument("--feed-dir", type=Path, default=None, help="feed directory with messages.jsonl and state.json")
        command.set_defaults(handler=handler)
        if name == "fetch":
            command.add_argument("--out", type=Path, required=True)
        else:
            command.add_argument("--snapshot", type=Path, required=True)
            command.add_argument("--diary", type=Path, required=True, help="JSON diary, created if missing and updated in place")
            command.add_argument("--report", type=Path, help="write the German report here")
    cycle = sub.add_parser("cycle", help="fetch and run in one step (for the 15-minute schedule)")
    cycle.add_argument("--feed-dir", type=Path, default=None)
    cycle.add_argument("--workdir", type=Path, required=True, help="folder for snapshot.json, diary.json and the report")
    cycle.set_defaults(handler=cmd_cycle)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
