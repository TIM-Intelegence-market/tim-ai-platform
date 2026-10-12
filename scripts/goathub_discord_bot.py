#!/usr/bin/env python3
"""GoatHub bot: read GoatHub community channels and export them for Claude's memory and TIM.

Subcommands:
  setup   ask for the channel ids, the mode (forward/direct) and your Discord user id;
          reuses the Broncx bot secret unless --secret-file points elsewhere
  sync    read every channel up to the newest message (whole history on the first
          run), then write the memory export; launchd runs this three times a day
  export  write the memory export from the stored messages only (no Discord access)
  calls   print the good community calls (grade A/B)
  import-screen FILE  store messages Claude read off your Discord window (JSON list), then export

The export goes to data/goathub_feed/memory/ and to every --memory-dir:
GOATHUB_KANAL.md (whole channel, verbatim), GOATHUB_KURZ.md (under 4 KB, for a
memory index) and goathub_calls.json (good calls, for TIM).

Setup guide: docs/knowledge/GOATHUB_DISCORD_FEED.md
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.goathub_feed import GoatHubFeedStore, good_calls, import_screen_readings, write_memory_export  # noqa: E402
from src.sources.broncx_discord import DiscordFeedError, load_bot_secret  # noqa: E402
from src.sources.goathub_discord import (  # noqa: E402
    GoatHubChannel,
    GoatHubConfig,
    GoatHubReader,
    default_config_path,
    default_secret_path,
)


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def setup(args: argparse.Namespace, ask: Callable[[str], str]) -> int:
    raw = [item.strip() for item in ask("Channel ID(s) to read, comma-separated (optionally id=name): ").split(",") if item.strip()]
    channels = tuple(GoatHubChannel(*(part.strip() for part in item.split("=", 1))) for item in raw)
    mode = (ask("Mode: 'forward' (you forward posts into your own channel) or 'direct' (bot invited into GoatHub) [forward]: ").strip() or "forward").lower()
    forwarders = [item.strip() for item in ask("Your Discord user ID (several: comma-separated; empty in direct mode): ").split(",") if item.strip()]
    config = GoatHubConfig(channels, mode, frozenset(forwarders))
    write_private(args.config, json.dumps(config.to_dict(), indent=2) + "\n")
    print(f"STORED config={args.config} channels={len(channels)} mode={mode}")
    if not args.secret_file.exists():
        print(f"Bot secret not found at {args.secret_file}: run 'scripts/broncx_discord_bot.py setup' first (same bot).")
    print("Next: python scripts/goathub_discord_bot.py sync")
    return 0


def _memory_dirs(args: argparse.Namespace) -> list[Path]:
    dirs = [args.feed_dir / "memory"]
    dirs += [path for path in args.memory_dir if path.expanduser().resolve() != dirs[0].resolve()]
    return dirs


def export(args: argparse.Namespace) -> int:
    written = write_memory_export(GoatHubFeedStore(args.feed_dir), _memory_dirs(args))
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} export files={len(written)} dirs={', '.join(str(path) for path in _memory_dirs(args))}", flush=True)
    return 0


def sync(args: argparse.Namespace) -> int:
    reader = GoatHubReader(load_bot_secret(args.secret_file), GoatHubConfig.load(args.config), GoatHubFeedStore(args.feed_dir))
    failed = False
    for channel in reader.config.channels:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            result = reader.sync_channel(channel)
        except DiscordFeedError as exc:
            print(f"{stamp} channel={channel.channel_id} ERROR: {exc}", flush=True)
            failed = True
            continue
        except OSError as exc:  # network down: export what we have, retry at the next run
            print(f"{stamp} channel={channel.channel_id} ERROR: network: {type(exc).__name__}", flush=True)
            failed = True
            continue
        print(f"{stamp} channel={channel.channel_id} fetched={result.fetched} stored={result.stored} duplicates={result.duplicates} "
              f"rejected_author={result.rejected_author} empty={result.skipped_empty} complete={result.complete}", flush=True)
        if result.skipped_empty and not result.stored:
            print("  hint: messages arrived without text; enable 'Message Content Intent' for the bot in the Developer Portal", flush=True)
    export(args)
    return 1 if failed else 0


def calls(args: argparse.Namespace) -> int:
    found = good_calls(GoatHubFeedStore(args.feed_dir).load(), reference_price=args.price)
    if not found:
        print(f"no good calls in {args.feed_dir}")
        return 0
    for call in found[: args.limit]:
        guidance = call.guidance
        print(f"{call.message.posted_at.isoformat(timespec='minutes')} {call.message.author_label} [{call.grade}] "
              f"{guidance.bias} {guidance.symbol or '?'} {guidance.timeframe or ''}".rstrip())
        print(f"  levels={[f'{level.role} {level.raw if level.ambiguous else level.value}' for level in guidance.levels]} "
              f"invalidation={list(guidance.invalidation)} reactions={call.message.reactions}")
        print(f"  text={call.message.content!r}")
    return 0


def main(argv: list[str] | None = None, ask: Callable[[str], str] = input) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["setup", "sync", "export", "calls", "import-screen"])
    parser.add_argument("file", nargs="?", type=Path, help="JSON file for 'import-screen'")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--secret-file", type=Path, default=default_secret_path())
    parser.add_argument("--feed-dir", type=Path, default=None, help="default: data/goathub_feed or $TIM_GOATHUB_FEED_DIR")
    parser.add_argument("--memory-dir", type=Path, action="append", default=[], help="extra directory for the memory export (repeatable)")
    parser.add_argument("--limit", type=int, default=20, help="calls shown by 'calls'")
    parser.add_argument("--price", type=Decimal, default=None, help="current price for 'calls' (scales shorthand like 82.6)")
    args = parser.parse_args(argv)
    if args.feed_dir is None:
        args.feed_dir = GoatHubFeedStore().root

    try:
        if args.command == "setup":
            return setup(args, ask)
        if args.command == "export":
            return export(args)
        if args.command == "calls":
            return calls(args)
        if args.command == "import-screen":
            if args.file is None:
                parser.error("import-screen needs a JSON file")
            stored, duplicates = import_screen_readings(GoatHubFeedStore(args.feed_dir), json.loads(args.file.read_text(encoding="utf-8")))
            print(f"import stored={stored} duplicates={duplicates}", flush=True)
            return export(args)
        return sync(args)
    except DiscordFeedError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
