#!/usr/bin/env python3
"""Three GoatHub channels read separately: calls, outcome check, scorecards and a board preview.

Subcommands:
  read      list the calls each channel reader finds (Broncx futures, goatfather spot, EyDu gold)
  evaluate  check every call against price bars and write scorecards plus the board text

Messages come from the bot's feed directory (``--feed-dir``, default data/goathub_feed) and/or
from screen transcripts (``--transcript FILE``, e.g. goathub-verlauf/kanaele/.../11-futures-t-1.md).
Price bars come from CSV files with open_time, open, high, low, close (``--bars BTC=btc_1h.csv``).
A symbol without bars is reported as "no price data", never guessed.

Nothing here posts to Discord: ``--board FILE`` writes the text a later #tim-live post would
carry, for review. Paper only, no orders.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.goathub_channels import (  # noqa: E402
    PROFILES,
    evaluate,
    load_bars_csv,
    parse_transcript,
    read_calls,
    render_board,
    scorecard,
)
from src.knowledge.goathub_feed import GoatHubFeedStore  # noqa: E402


def _messages(args: argparse.Namespace) -> list:
    messages = []
    if args.feed_dir is not None or not args.transcript:
        messages.extend(GoatHubFeedStore(args.feed_dir).load())
    for path in args.transcript or ():
        messages.extend(parse_transcript(Path(path)))
    unique = {message.message_id: message for message in messages}
    return list(unique.values())


def _observed_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SystemExit("--observed-at needs a time zone, e.g. 2026-10-29T12:00:00+00:00")
    return parsed.astimezone(timezone.utc)


def cmd_read(args: argparse.Namespace) -> int:
    calls = read_calls(_messages(args))
    payload = {key: [item.to_dict() for item in items] for key, items in calls.items()}
    for key, items in calls.items():
        grades = {grade: sum(1 for item in items if item.call.grade == grade) for grade in ("A", "B", "C")}
        print(f"{PROFILES[key].title}: {len(items)} calls (A {grades['A']}, B {grades['B']}, C {grades['C']})")
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    observed_at = _observed_at(args.observed_at)
    bars = {}
    for item in args.bars or ():
        symbol, _, path = item.partition("=")
        if not path:
            raise SystemExit(f"--bars expects SYMBOL=FILE, got {item!r}")
        bars[symbol.upper()] = load_bars_csv(Path(path))
    outcomes = evaluate(read_calls(_messages(args)), bars, observed_at=observed_at)
    cards = {key: scorecard(items) for key, items in outcomes.items()}
    for key, card in cards.items():
        rate = "n/a" if card["hit_rate"] is None else f"{card['hit_rate'] * 100:.0f}% of {card['hit_rate_basis']} with target and stop"
        print(f"{PROFILES[key].title}: {card['target_hit']} targets, {card['stopped']} stops, {card['open']} open, "
              f"{card['expired']} expired, hit rate {rate}; not checkable {card['not_checkable']}, no price data {card['no_price_data']}")
    if args.out:
        payload = {
            "observed_at": observed_at.isoformat(),
            "rule": "GoatHub calls are hypotheses: outcomes and scorecards describe the past, they are no signal and no advice",
            "scorecards": cards,
            "outcomes": {key: [item.to_dict() for item in items] for key, items in outcomes.items()},
        }
        Path(args.out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if args.board:
        Path(args.board).write_text(render_board(outcomes, generated_at=observed_at) + "\n", encoding="utf-8")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("read", cmd_read), ("evaluate", cmd_evaluate)):
        command = sub.add_parser(name)
        command.add_argument("--feed-dir", type=Path, default=None, help="bot feed directory (default data/goathub_feed when no transcript is given)")
        command.add_argument("--transcript", action="append", help="screen transcript Markdown file; repeatable")
        command.add_argument("--out", help="write JSON here")
        command.set_defaults(handler=handler)
        if name == "evaluate":
            command.add_argument("--bars", action="append", help="SYMBOL=CSV with open_time,open,high,low,close; repeatable")
            command.add_argument("--observed-at", help="evaluate as of this time (ISO 8601 with zone); default now")
            command.add_argument("--board", help="write the board preview text here (never posted)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
