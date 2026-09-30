"""Read-only Discord poller for the Broncx feed channel in the TIM owner's own server.

The owner forwards Broncx messages (Discord "Forward") into one channel of
their own server; a bot the owner created reads that channel over the Discord
REST API and stores each post in ``BroncxFeedStore``. The bot never writes to
Discord, never joins foreign servers and never automates a user account.

Only messages from the configured forwarder ids are accepted, so other members
of the owner's server cannot inject "Broncx" posts. Forwarded messages carry
the original text and timestamp in ``message_snapshots``; Discord does not
include the original author there, so the attribution rests on the channel
being used for Broncx forwards only.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from config.secrets import SecretValue
from src.knowledge.broncx_feed import SOURCE_FORWARD, SOURCE_MANUAL, BroncxFeedStore, BroncxPost

__all__ = [
    "API_BASE",
    "DiscordFeedConfig",
    "DiscordFeedError",
    "DiscordFeedPoller",
    "PollResult",
    "default_config_path",
    "default_secret_path",
    "load_bot_secret",
    "message_to_post",
]

API_BASE = "https://discord.com/api/v10"
USER_AGENT = "DiscordBot (https://github.com/uezeyiraydin-cell/tim-ai-platform, 1.0)"
_SNOWFLAKE = re.compile(r"\d{15,21}")
_FORWARD_REFERENCE_TYPE = 1
INITIAL_BACKFILL = 50

HttpGet = Callable[[str, dict[str, str]], tuple[int, Any, dict[str, str]]]


class DiscordFeedError(RuntimeError):
    """Configuration or access problem; the message never contains the bot secret."""


def _support_dir() -> Path:
    home = Path.home()
    mac = home / "Library" / "Application Support" / "TIM"
    return mac if mac.parent.exists() else home / ".config" / "tim"


def default_secret_path() -> Path:
    return Path(os.environ.get("TIM_BRONCX_DISCORD_SECRET_FILE") or _support_dir() / "broncx-discord-bot").expanduser()


def default_config_path() -> Path:
    return Path(os.environ.get("TIM_BRONCX_DISCORD_CONFIG") or _support_dir() / "broncx-discord.json").expanduser()


@dataclass(frozen=True, slots=True)
class DiscordFeedConfig:
    channel_id: str
    forwarder_ids: frozenset[str]

    def __post_init__(self) -> None:
        if not _SNOWFLAKE.fullmatch(self.channel_id):
            raise DiscordFeedError("channel_id must be a Discord id (15-21 digits); enable Developer Mode and use 'Copy Channel ID'")
        if not self.forwarder_ids or not all(_SNOWFLAKE.fullmatch(item) for item in self.forwarder_ids):
            raise DiscordFeedError("forwarder_ids must list at least one Discord user id (15-21 digits)")

    @classmethod
    def load(cls, path: Path) -> "DiscordFeedConfig":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise DiscordFeedError(f"config file missing: {path}; run 'broncx_discord_bot.py setup'") from exc
        except ValueError as exc:
            raise DiscordFeedError(f"config file is not valid JSON: {path}") from exc
        return cls(str(payload.get("channel_id", "")), frozenset(str(item) for item in payload.get("forwarder_ids", ())))

    def to_dict(self) -> dict[str, Any]:
        return {"channel_id": self.channel_id, "forwarder_ids": sorted(self.forwarder_ids)}


def load_bot_secret(path: Path) -> SecretValue:
    try:
        info = path.stat()
    except FileNotFoundError as exc:
        raise DiscordFeedError(f"bot secret file missing: {path}; run 'broncx_discord_bot.py setup'") from exc
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise DiscordFeedError(f"bot secret file must be private (chmod 600): {path}")
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise DiscordFeedError(f"bot secret file is empty: {path}")
    return SecretValue(value)


@dataclass(frozen=True, slots=True)
class PollResult:
    fetched: int
    stored: int
    duplicates: int
    rejected_author: int
    skipped_empty: int
    last_message_id: str | None


def message_to_post(message: dict[str, Any], received_at: datetime) -> BroncxPost | None:
    """Map a Discord message (forward or typed/pasted text) to a feed post."""
    snapshots = message.get("message_snapshots") or []
    reference = message.get("message_reference") or {}
    if snapshots and reference.get("type", _FORWARD_REFERENCE_TYPE) == _FORWARD_REFERENCE_TYPE:
        original = snapshots[0].get("message") or {}
        content = str(original.get("content") or "")
        posted_at = original.get("timestamp") or message["timestamp"]
        attachments = original.get("attachments") or []
        source, note = SOURCE_FORWARD, str(message.get("content") or "")
        message_id = str(reference.get("message_id") or message["id"])
    else:
        content = str(message.get("content") or "")
        posted_at = message["timestamp"]
        attachments = message.get("attachments") or []
        source, note = SOURCE_MANUAL, ""
        message_id = str(message["id"])
    names = tuple(str(item.get("filename") or item.get("url") or "attachment") for item in attachments)
    if not content.strip() and not names:
        return None
    return BroncxPost(
        message_id=message_id,
        posted_at=_parse_time(posted_at),
        content=content,
        received_at=received_at,
        source=source,
        attachments=names,
        forwarded_by=str((message.get("author") or {}).get("id", "")),
        note=note,
    )


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _urllib_get(url: str, headers: dict[str, str]) -> tuple[int, Any, dict[str, str]]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read().decode("utf-8")), dict(response.headers)
    except urllib.error.HTTPError as error:
        try:
            body = json.loads(error.read().decode("utf-8"))
        except ValueError:
            body = {}
        return error.code, body, dict(error.headers or {})


class DiscordFeedPoller:
    def __init__(
        self,
        secret: SecretValue,
        config: DiscordFeedConfig,
        store: BroncxFeedStore,
        http_get: HttpGet | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._secret = secret
        self.config = config
        self.store = store
        self._http_get = http_get or _urllib_get
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep

    def poll_once(self) -> PollResult:
        after = self.store.last_message_id()
        query = f"after={after}&limit=100" if after else f"limit={INITIAL_BACKFILL}"
        messages = self._get(f"{API_BASE}/channels/{self.config.channel_id}/messages?{query}")
        if not isinstance(messages, list):
            raise DiscordFeedError("unexpected Discord response shape")

        stored = duplicates = rejected = empty = 0
        newest = after
        received_at = self._clock()
        for message in sorted((item for item in messages if _SNOWFLAKE.fullmatch(str(item.get("id", "")))), key=lambda item: int(item["id"])):
            newest = str(message["id"]) if newest is None or int(message["id"]) > int(newest) else newest
            author = message.get("author") or {}
            if author.get("bot") or str(author.get("id", "")) not in self.config.forwarder_ids:
                rejected += 1
                continue
            try:
                post = message_to_post(message, received_at)
            except (KeyError, TypeError, ValueError):
                post = None  # one malformed message must not block the cursor forever
            if post is None:
                empty += 1
                continue
            if self.store.append(post):
                stored += 1
            else:
                duplicates += 1
        if newest and newest != after:
            self.store.set_last_message_id(newest)
        return PollResult(len(messages), stored, duplicates, rejected, empty, newest)

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
                raise DiscordFeedError("channel not found (404); check channel_id and that the bot is in your server")
            raise DiscordFeedError(f"Discord request failed with HTTP {status}")
        raise DiscordFeedError("Discord kept rate-limiting the request; try again later")
