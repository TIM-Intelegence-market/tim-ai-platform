#!/usr/bin/env python3
"""Broncx feed bot: read forwarded Broncx posts from your own Discord channel.

Subcommands:
  setup   ask for channel id, your Discord user id and the bot secret (hidden
          input); writes the config and a private (0600) secret file
  once    poll the channel once and store new posts
  run     poll every --interval seconds (for launchd)
  show    print the stored posts and how TIM currently parses them

Setup guide: docs/knowledge/BRONCX_DISCORD_FEED.md
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.broncx_feed import BroncxFeedStore, parse_guidance  # noqa: E402
from src.sources.broncx_discord import (  # noqa: E402
    DiscordFeedConfig,
    DiscordFeedError,
    DiscordFeedPoller,
    PollResult,
    default_config_path,
    default_secret_path,
    load_bot_secret,
)


def write_private(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(value)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def setup(args: argparse.Namespace, ask: Callable[[str], str], ask_hidden: Callable[[str], str]) -> int:
    channel = ask("Channel ID of your #broncx-feed channel: ").strip()
    forwarders = [item.strip() for item in ask("Your Discord user ID (several: comma-separated): ").split(",") if item.strip()]
    config = DiscordFeedConfig(channel, frozenset(forwarders))
    secret = ask_hidden("Bot secret from the Developer Portal (input hidden): ").strip()
    if not secret or any(character.isspace() for character in secret):
        print("NOT STORED: the bot secret is empty or contains spaces/line breaks.")
        return 2
    write_private(args.config, json.dumps(config.to_dict(), indent=2) + "\n")
    write_private(args.secret_file, secret)
    print(f"STORED config={args.config} secret_file={args.secret_file} mode=0600 length={len(secret)}")
    print("Next: python scripts/broncx_discord_bot.py once")
    return 0


def _poller(args: argparse.Namespace) -> DiscordFeedPoller:
    return DiscordFeedPoller(load_bot_secret(args.secret_file), DiscordFeedConfig.load(args.config), BroncxFeedStore(args.feed_dir))


def _report(result: PollResult) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} fetched={result.fetched} stored={result.stored} duplicates={result.duplicates} "
          f"rejected_author={result.rejected_author} empty={result.skipped_empty}", flush=True)
    if result.skipped_empty and not result.stored:
        print("  hint: messages arrived without text; enable 'Message Content Intent' for the bot in the Developer Portal", flush=True)


def show(args: argparse.Namespace) -> int:
    posts = BroncxFeedStore(args.feed_dir).load()
    if not posts:
        print(f"no posts in {args.feed_dir}")
        return 0
    for post in posts[-args.limit:]:
        guidance = parse_guidance(post.content)
        print(f"{post.posted_at.isoformat(timespec='minutes')} [{post.source}] {post.content!r}")
        print(f"  bias={guidance.bias} symbol={guidance.symbol} timeframe={guidance.timeframe} "
              f"levels={[level.raw for level in guidance.levels]} invalidation={list(guidance.invalidation)} "
              f"attachments={len(post.attachments)} quality={guidance.parse_quality}")
    return 0


def main(argv: list[str] | None = None, ask: Callable[[str], str] = input, ask_hidden: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["setup", "once", "run", "show"])
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--secret-file", type=Path, default=default_secret_path())
    parser.add_argument("--feed-dir", type=Path, default=None, help="default: data/broncx_feed or $TIM_BRONCX_FEED_DIR")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between polls for 'run' (minimum 15)")
    parser.add_argument("--limit", type=int, default=20, help="posts shown by 'show'")
    args = parser.parse_args(argv)
    if args.feed_dir is None:
        args.feed_dir = BroncxFeedStore().root

    try:
        if args.command == "setup":
            return setup(args, ask, ask_hidden)
        if args.command == "show":
            return show(args)
        poller = _poller(args)
        if args.command == "once":
            _report(poller.poll_once())
            return 0
        interval = max(args.interval, 15.0)
        while True:
            try:
                _report(poller.poll_once())
            except DiscordFeedError as exc:
                print(f"ERROR: {exc}", flush=True)
            except OSError as exc:  # network down: keep the service alive, retry next cycle
                print(f"ERROR: network: {type(exc).__name__}", flush=True)
            except ValueError as exc:  # e.g. a non-JSON reply from a proxy; retry next cycle
                print(f"ERROR: unexpected response: {type(exc).__name__}", flush=True)
            time.sleep(interval)
    except DiscordFeedError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
