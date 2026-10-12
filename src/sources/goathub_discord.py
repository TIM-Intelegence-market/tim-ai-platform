"""Read-only Discord reader for GoatHub community channels.

Two modes, chosen in the config:

- ``forward`` (default): GoatHub posts are forwarded (Discord "Forward") into a
  channel of the TIM owner's own server, as with the Broncx feed. Only
  messages from the configured forwarder ids are accepted. Discord does not
  include the original author in a forward, so such messages show no author.
- ``direct``: the GoatHub server's admins invited the bot into their server.
  The bot then reads the configured channels with author names, and accepts
  every human author there (bots are skipped).

The bot never writes to Discord and never automates a user account. It reuses
the Broncx bot secret by default (one bot, several channels).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config.secrets import SecretValue
from src.knowledge.goathub_feed import SOURCE_DIRECT, SOURCE_FORWARD, SOURCE_MANUAL, GoatHubFeedStore, GoatHubMessage
from src.sources.broncx_discord import (
    API_BASE,
    DiscordFeedError,
    HttpGet,
    _parse_time,
    _support_dir,
    _urllib_get,
)
from src.sources.broncx_discord import default_secret_path as broncx_secret_path

__all__ = [
    "GoatHubChannel",
    "GoatHubConfig",
    "GoatHubReader",
    "SyncResult",
    "default_config_path",
    "default_secret_path",
    "message_to_goathub",
]

MODES = ("forward", "direct")
PAGE_SIZE = 100
# One sync reads at most this many pages per channel (10,000 messages); the rest follows on the next run.
MAX_PAGES = 100
_SNOWFLAKE = re.compile(r"\d{15,21}")
_FORWARD_REFERENCE_TYPE = 1
USER_AGENT = "DiscordBot (https://github.com/uezeyiraydin-cell/tim-ai-platform, 1.0)"


def default_secret_path() -> Path:
    override = os.environ.get("TIM_GOATHUB_DISCORD_SECRET_FILE")
    return Path(override).expanduser() if override else broncx_secret_path()


def default_config_path() -> Path:
    return Path(os.environ.get("TIM_GOATHUB_DISCORD_CONFIG") or _support_dir() / "goathub-discord.json").expanduser()


@dataclass(frozen=True, slots=True)
class GoatHubChannel:
    channel_id: str
    name: str = ""

    def __post_init__(self) -> None:
        if not _SNOWFLAKE.fullmatch(self.channel_id):
            raise DiscordFeedError("channel id must be a Discord id (15-21 digits); enable Developer Mode and use 'Copy Channel ID'")


@dataclass(frozen=True, slots=True)
class GoatHubConfig:
    channels: tuple[GoatHubChannel, ...]
    mode: str = "forward"
    forwarder_ids: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.channels:
            raise DiscordFeedError("config needs at least one channel")
        if self.mode not in MODES:
            raise DiscordFeedError(f"mode must be one of {', '.join(MODES)}")
        if self.mode == "forward" and not self.forwarder_ids:
            raise DiscordFeedError("forward mode needs forwarder_ids (your Discord user id)")
        if not all(_SNOWFLAKE.fullmatch(item) for item in self.forwarder_ids):
            raise DiscordFeedError("forwarder_ids must be Discord user ids (15-21 digits)")
        if self.forwarder_ids & {channel.channel_id for channel in self.channels}:
            raise DiscordFeedError("a channel id equals a forwarder (user) id; enter the channel id via 'Copy Channel ID', not your user id")

    @classmethod
    def load(cls, path: Path) -> "GoatHubConfig":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DiscordFeedError(f"config file missing: {path}; run 'goathub_discord_bot.py setup'") from exc
        except ValueError as exc:
            raise DiscordFeedError(f"config file is not valid JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise DiscordFeedError(f"config file must hold a JSON object: {path}")
        channels = tuple(
            GoatHubChannel(str(item.get("id", "")), str(item.get("name") or "")) if isinstance(item, dict) else GoatHubChannel(str(item))
            for item in payload.get("channels") or ()
        )
        return cls(channels, str(payload.get("mode") or "forward"), frozenset(str(item) for item in payload.get("forwarder_ids") or ()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "channels": [{"id": channel.channel_id, "name": channel.name} for channel in self.channels],
            "mode": self.mode,
            "forwarder_ids": sorted(self.forwarder_ids),
        }


@dataclass(frozen=True, slots=True)
class SyncResult:
    channel_id: str
    fetched: int
    stored: int
    duplicates: int
    rejected_author: int
    skipped_empty: int
    complete: bool  # False: MAX_PAGES reached, the next run continues


def _reaction_count(message: dict[str, Any]) -> int:
    total = 0
    for item in message.get("reactions") or ():
        try:
            total += max(int(item.get("count") or 0), 0)
        except (TypeError, ValueError, AttributeError):
            continue
    return total


def message_to_goathub(message: dict[str, Any], channel: GoatHubChannel, received_at: datetime, mode: str = "direct") -> GoatHubMessage | None:
    """Map a Discord message (direct post, forward or typed text) to a stored community message."""
    author = message.get("author") or {}
    snapshots = message.get("message_snapshots") or []
    reference = message.get("message_reference") or {}
    if snapshots and reference.get("type", _FORWARD_REFERENCE_TYPE) == _FORWARD_REFERENCE_TYPE:
        original = snapshots[0].get("message") or {}
        content = str(original.get("content") or "")
        posted_at = original.get("timestamp") or message["timestamp"]
        attachments = original.get("attachments") or []
        source, author_id, author_name = SOURCE_FORWARD, "", ""
        forwarded_by = str(author.get("id", ""))
        message_id = str(reference.get("message_id") or message["id"])
    else:
        content = str(message.get("content") or "")
        posted_at = message["timestamp"]
        attachments = message.get("attachments") or []
        source = SOURCE_DIRECT if mode == "direct" else SOURCE_MANUAL
        author_id = str(author.get("id", ""))
        author_name = str(author.get("global_name") or author.get("username") or "")
        forwarded_by = ""
        message_id = str(message["id"])
    names = tuple(str(item.get("filename") or item.get("url") or "attachment") for item in attachments)
    if not content.strip() and not names:
        return None
    return GoatHubMessage(
        message_id=message_id,
        channel_id=channel.channel_id,
        posted_at=_parse_time(posted_at),
        content=content,
        received_at=received_at,
        author_id=author_id,
        author_name=author_name,
        channel_name=channel.name,
        source=source,
        attachments=names,
        reactions=_reaction_count(message),
        forwarded_by=forwarded_by,
    )


class GoatHubReader:
    def __init__(
        self,
        secret: SecretValue,
        config: GoatHubConfig,
        store: GoatHubFeedStore,
        http_get: HttpGet | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] | None = None,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self._secret = secret
        self.config = config
        self.store = store
        self._http_get = http_get or _urllib_get
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or time.sleep
        self.max_pages = max_pages

    def sync(self) -> list[SyncResult]:
        """Read every configured channel from its cursor to the newest message (whole history on the first run)."""
        return [self.sync_channel(channel) for channel in self.config.channels]

    def sync_channel(self, channel: GoatHubChannel) -> SyncResult:
        after = self.store.cursors().get(channel.channel_id, "0")
        fetched = stored = duplicates = rejected = empty = 0
        complete = False
        for _ in range(self.max_pages):
            page = self._get(f"{API_BASE}/channels/{channel.channel_id}/messages?after={after}&limit={PAGE_SIZE}")
            if not isinstance(page, list):
                raise DiscordFeedError("unexpected Discord response shape")
            valid = sorted((item for item in page if _SNOWFLAKE.fullmatch(str(item.get("id", "")))), key=lambda item: int(item["id"]))
            fetched += len(page)
            received_at = self._clock()
            for message in valid:
                if not self._accepted(message):
                    rejected += 1
                    continue
                try:
                    item = message_to_goathub(message, channel, received_at, self.config.mode)
                except (KeyError, TypeError, ValueError):
                    item = None  # one malformed message must not block the cursor forever
                if item is None:
                    empty += 1
                elif self.store.append(item):
                    stored += 1
                else:
                    duplicates += 1
            if valid:
                after = str(valid[-1]["id"])
                self.store.set_cursor(channel.channel_id, after)
            if len(page) < PAGE_SIZE:
                complete = True
                break
        return SyncResult(channel.channel_id, fetched, stored, duplicates, rejected, empty, complete)

    def _accepted(self, message: dict[str, Any]) -> bool:
        author = message.get("author") or {}
        if author.get("bot"):
            return False
        if self.config.mode == "direct":
            return True
        return str(author.get("id", "")) in self.config.forwarder_ids

    def _get(self, url: str) -> Any:
        headers = {"Authorization": f"Bot {self._secret.reveal()}", "User-Agent": USER_AGENT}
        for _ in range(3):
            status, body, response_headers = self._http_get(url, headers)
            if status == 200:
                return body
            if status == 429:
                retry_after = float((body or {}).get("retry_after") or response_headers.get("Retry-After") or 5)
                self._sleep(min(max(retry_after, 0.5), 60.0))
                continue
            if status == 401:
                raise DiscordFeedError("Discord rejected the bot secret (401); reset it in the Developer Portal and run setup again")
            if status == 403:
                raise DiscordFeedError("bot cannot read the channel (403); give it 'View Channel' and 'Read Message History' there")
            if status == 404:
                raise DiscordFeedError("channel not found (404); check the channel id and that the bot is in that server")
            raise DiscordFeedError(f"Discord request failed with HTTP {status}")
        raise DiscordFeedError("Discord kept rate-limiting the request; try again later")

