#!/usr/bin/env python3
"""Broncx feed bot: read forwarded Broncx posts from your own Discord channel.

Subcommands:
  setup   ask for channel id, your Discord user id and the bot secret (hidden
          input); writes the config and a private (0600) secret file
  once    poll the channel once and store new posts
  run     poll every --interval seconds (for launchd)
  show    print the stored posts and how TIM currently parses them
  fetch-images  download chart images of posts stored before image support
  read-charts   read not-yet-read chart images with the local vision model (Ollama)

'once' and 'run' also download chart images of new posts; 'run' then reads them.

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
from decimal import Decimal
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.knowledge.broncx_chart_vision import ChartImageStore, OllamaVision, VisionError, guidance_for_post  # noqa: E402
from src.knowledge.broncx_feed import BroncxFeedStore  # noqa: E402
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
          f"rejected_author={result.rejected_author} empty={result.skipped_empty} "
          f"images={result.images_saved} image_errors={result.image_errors}", flush=True)
    if result.skipped_empty and not result.stored:
        print("  hint: messages arrived without text; enable 'Message Content Intent' for the bot in the Developer Portal", flush=True)


def read_charts(args: argparse.Namespace, limit: int) -> int:
    """Read pending chart images; returns how many were read. Model errors are reported, not raised."""
    store = BroncxFeedStore(args.feed_dir)
    try:
        readings = ChartImageStore(store.root).read_pending(store.load(), OllamaVision(args.vision_model), limit=limit)
    except VisionError as exc:
        print(f"ERROR: chart reading: {exc}", flush=True)
        return 0
    for reading in readings:
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        detail = reading.error or f"bias={reading.bias} levels={[str(price) for price, _ in reading.levels]}"
        print(f"{stamp} chart {reading.image}: {detail}", flush=True)
    return len(readings)


def show(args: argparse.Namespace) -> int:
    store = BroncxFeedStore(args.feed_dir)
    posts = store.load()
    if not posts:
        print(f"no posts in {args.feed_dir}")
        return 0
    images = ChartImageStore(store.root)
    for post in posts[-args.limit:]:
        guidance = guidance_for_post(post, args.price)
        print(f"{post.posted_at.isoformat(timespec='minutes')} [{post.source}] {post.content!r}")
        print(f"  bias={guidance.bias} symbol={guidance.symbol} timeframe={guidance.timeframe} "
              f"levels={[level.raw for level in guidance.levels]} invalidation={list(guidance.invalidation)} "
              f"attachments={len(post.attachments)} quality={guidance.parse_quality}")
        saved = images.images_for(post.message_id)
        if post.attachments and not saved:
            print("  chart: image not downloaded (run 'fetch-images')")
        elif saved and not post.chart_readings:
            print(f"  chart: {len(saved)} image(s) saved, not read yet (run 'read-charts')")
        for reading in post.chart_readings:
            levels = [f"{price}{' ' + label if label else ''}" for price, label in reading.levels]
            invalid = [f"{side} {price}" for side, price in reading.invalidation]
            print(f"  chart (estimated, {reading.model}): bias={reading.bias} symbol={reading.symbol} timeframe={reading.timeframe} "
                  f"levels={levels} invalidation={invalid} text={reading.text!r}")
        for note in guidance.notes:
            print(f"  note: {note}")
    return 0


def main(argv: list[str] | None = None, ask: Callable[[str], str] = input, ask_hidden: Callable[[str], str] = getpass.getpass) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["setup", "once", "run", "show", "fetch-images", "read-charts"])
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--secret-file", type=Path, default=default_secret_path())
    parser.add_argument("--feed-dir", type=Path, default=None, help="default: data/broncx_feed or $TIM_BRONCX_FEED_DIR")
    parser.add_argument("--interval", type=float, default=60.0, help="seconds between polls for 'run' (minimum 15)")
    parser.add_argument("--limit", type=int, default=20, help="posts shown by 'show'")
    parser.add_argument("--price", type=Decimal, default=None, help="current price for 'show' (scales shorthand like 82.6 and checks chart levels)")
    parser.add_argument("--vision-model", default=None, help="Ollama vision model (default: $TIM_BRONCX_VISION_MODEL or qwen3.5:9b)")
    parser.add_argument("--no-charts", action="store_true", help="'run' without reading chart images")
    args = parser.parse_args(argv)
    if args.feed_dir is None:
        args.feed_dir = BroncxFeedStore().root

    try:
        if args.command == "setup":
            return setup(args, ask, ask_hidden)
        if args.command == "show":
            return show(args)
        if args.command == "read-charts":
            read_charts(args, limit=1000)
            return 0
        poller = _poller(args)
        if args.command == "once":
            _report(poller.poll_once())
            return 0
        if args.command == "fetch-images":
            saved, errors = poller.backfill_images()
            print(f"images={saved} image_errors={errors}")
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
            if not args.no_charts:
                read_charts(args, limit=1)  # one image per cycle (about a minute each), so polling keeps going
            time.sleep(interval)
    except DiscordFeedError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
