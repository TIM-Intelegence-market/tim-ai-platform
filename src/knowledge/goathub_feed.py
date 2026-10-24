"""GoatHub community feed: stored channel messages, community calls and a memory export.

Messages come from Discord channels read by ``src/sources/goathub_discord.py``:
either a channel in the TIM owner's own server that GoatHub posts are forwarded
into, or GoatHub channels the bot was invited to by the server's admins. This
module stores them verbatim, finds the trading calls among them and writes the
whole channel as Markdown, so Claude's memory and TIM read the real messages.

Status: community opinion, observation-only. A call is a hypothesis with levels
TIM can check against candles; it is never market evidence, never a
confirmation and never an instruction. The grade only says how complete a call
is written (direction, symbol, level, invalidation), not whether it is right.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Sequence

from .broncx_feed import BroncxGuidance, parse_guidance

__all__ = [
    "CHANNEL_ROLES",
    "CommunityCall",
    "GoatHubFeedStore",
    "GoatHubMessage",
    "ROLE_CALLS",
    "ROLE_KNOWLEDGE",
    "default_goathub_dir",
    "extract_call",
    "good_calls",
    "import_screen_readings",
    "render_channel_markdown",
    "render_summary_markdown",
    "write_memory_export",
]

SOURCE_DIRECT = "discord_direct"
SOURCE_FORWARD = "discord_forward"
SOURCE_SCREEN = "discord_screen"  # read off the owner's own Discord window by Claude; transcribed, check the original when it matters
SOURCE_FOLLOW = "discord_follow"  # Discord channel "Follow": the original channel posts into the owner's channel
SOURCE_MANUAL = "discord_manual"
# What a channel is for. "calls": messages are checked for trade calls. "knowledge": teaching
# material (e.g. education, bootcamp); kept verbatim for reading, never turned into calls.
ROLE_CALLS = "calls"
ROLE_KNOWLEDGE = "knowledge"
CHANNEL_ROLES = (ROLE_CALLS, ROLE_KNOWLEDGE)
GOOD_GRADES = ("A", "B")
# Reactions that make a call "liked by the community"; a count, not a vote on correctness.
POPULAR_REACTIONS = 3
SUMMARY_LIMIT_BYTES = 3800


def default_goathub_dir() -> Path:
    """Local, untracked feed directory (``data/`` is git-ignored)."""
    override = os.environ.get("TIM_GOATHUB_FEED_DIR")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "goathub_feed"


def _stored_role(value: Any) -> str:
    """Older lines have no role (they were all read as calls); an unknown value never becomes a call."""
    if value in (None, ""):
        return ROLE_CALLS
    return str(value) if str(value) in CHANNEL_ROLES else ROLE_KNOWLEDGE


@dataclass(frozen=True, slots=True)
class GoatHubMessage:
    message_id: str
    channel_id: str
    posted_at: datetime
    content: str
    received_at: datetime
    author_id: str = ""
    author_name: str = ""
    channel_name: str = ""
    source: str = SOURCE_DIRECT
    attachments: tuple[str, ...] = ()
    reactions: int = 0
    forwarded_by: str = ""
    channel_role: str = ROLE_CALLS  # recorded when the message is stored; see CHANNEL_ROLES

    def __post_init__(self) -> None:
        if not self.message_id or not self.channel_id:
            raise ValueError("message_id and channel_id are required")
        if self.channel_role not in CHANNEL_ROLES:
            raise ValueError(f"channel_role must be one of {', '.join(CHANNEL_ROLES)}")
        if self.posted_at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("message timestamps must be timezone-aware")
        if not self.content.strip() and not self.attachments:
            raise ValueError("message has neither text nor attachments")

    @property
    def known_at(self) -> datetime:
        """When TIM could first know the message: posted, and also received by the bot."""
        return max(self.posted_at, self.received_at)

    @property
    def author_label(self) -> str:
        if self.source == SOURCE_FORWARD and not self.author_name:
            return "weitergeleitet (Autor unbekannt)"
        return self.author_name or self.author_id or "unbekannt"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["posted_at"] = self.posted_at.isoformat()
        payload["received_at"] = self.received_at.isoformat()
        payload["attachments"] = list(self.attachments)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GoatHubMessage":
        return cls(
            message_id=str(payload["message_id"]),
            channel_id=str(payload["channel_id"]),
            posted_at=datetime.fromisoformat(payload["posted_at"]),
            content=str(payload.get("content") or ""),
            received_at=datetime.fromisoformat(payload["received_at"]),
            author_id=str(payload.get("author_id") or ""),
            author_name=str(payload.get("author_name") or ""),
            channel_name=str(payload.get("channel_name") or ""),
            source=str(payload.get("source") or SOURCE_DIRECT),
            attachments=tuple(str(item) for item in payload.get("attachments") or ()),
            reactions=int(payload.get("reactions") or 0),
            forwarded_by=str(payload.get("forwarded_by") or ""),
            channel_role=_stored_role(payload.get("channel_role")),
        )


class GoatHubFeedStore:
    """Append-only JSONL store, idempotent by (channel, message id), with one cursor per channel."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_goathub_dir()
        self.messages_path = self.root / "messages.jsonl"
        self.state_path = self.root / "state.json"
        self._known: set[tuple[str, str]] | None = None

    def load(self) -> list[GoatHubMessage]:
        if not self.messages_path.exists():
            return []
        messages: dict[tuple[str, str], GoatHubMessage] = {}
        for line in self.messages_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                message = GoatHubMessage.from_dict(json.loads(line))
            except (ValueError, KeyError, TypeError):
                continue  # a torn last line after a crash must not hide the other messages
            messages.setdefault((message.channel_id, message.message_id), message)
        return sorted(messages.values(), key=lambda item: (item.posted_at, item.channel_id, item.message_id))

    def append(self, message: GoatHubMessage) -> bool:
        if self._known is None:
            self._known = {(item.channel_id, item.message_id) for item in self.load()}
        key = (message.channel_id, message.message_id)
        if key in self._known:
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        torn = self.messages_path.exists() and self.messages_path.stat().st_size > 0 and not self.messages_path.read_bytes().endswith(b"\n")
        with self.messages_path.open("a", encoding="utf-8") as stream:
            if torn:
                stream.write("\n")
            stream.write(json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        self._known.add(key)
        return True

    def cursors(self) -> dict[str, str]:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8")).get("cursors") or {}
        except (OSError, ValueError, AttributeError):
            return {}
        return {str(key): str(item) for key, item in value.items() if item} if isinstance(value, dict) else {}

    def set_cursor(self, channel_id: str, message_id: str) -> None:
        cursors = self.cursors()
        cursors[channel_id] = message_id
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"cursors": cursors}, sort_keys=True), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def messages_until(self, observed_at: datetime) -> list[GoatHubMessage]:
        """Messages TIM already had at ``observed_at`` (no lookahead in replays)."""
        return [message for message in self.load() if message.known_at <= observed_at]


@dataclass(frozen=True, slots=True)
class CommunityCall:
    message: GoatHubMessage
    guidance: BroncxGuidance
    grade: str  # A: direction, symbol, level and invalidation/stop | B: direction, symbol and level | C: the rest
    reasons: tuple[str, ...]

    @property
    def is_good(self) -> bool:
        return self.grade in GOOD_GRADES

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message.message_id,
            "channel_id": self.message.channel_id,
            "channel_name": self.message.channel_name,
            "author": self.message.author_label,
            "author_id": self.message.author_id,
            "posted_at": self.message.posted_at.isoformat(),
            "reactions": self.message.reactions,
            "text": self.message.content,
            "grade": self.grade,
            "reasons": list(self.reasons),
            "guidance": self.guidance.to_dict(),
        }


# Community posts name any coin ("long on movr", "Long HNT"); Broncx' parser only knows a few majors.
_TICKER_AFTER_DIRECTION = re.compile(
    r"\b(?:long|longing|short|shorting|buy|buying|sell|selling)\s+(?:on\s+|a\s+|some\s+)?\$?([A-Za-z][A-Za-z0-9]{1,9})\b", re.IGNORECASE)
_TICKER_PAIR = re.compile(r"\b([A-Za-z][A-Za-z0-9]{1,9})\s*/\s*USDT?\b", re.IGNORECASE)
_NOT_TICKERS = {
    "from", "here", "now", "the", "it", "this", "that", "more", "before", "after", "on", "at", "with", "and", "or",
    "position", "positions", "weekly", "daily", "spot", "futures", "dip", "dips", "every", "all", "some", "zone",
    "breakout", "entry", "only", "again", "too", "back", "what", "whatever", "when", "if", "is", "in", "for", "you",
}
# "2-5% of account", "0.5-1% each 5% dip": sizes and percentages, never price levels.
_PERCENT = re.compile(r"\d+(?:[.,]\d+)?\s*(?:-|to)\s*\d+(?:[.,]\d+)?\s*%|\d+(?:[.,]\d+)?\s*%")
# "SL on 1.5$" means the same as "SL at 1.5".
_SL_ON = re.compile(r"\b(sl|stop(?:\s?loss)?)\s+on\b", re.IGNORECASE)
# "Pull SL little lower to 0.48" moves the stop; the number is a stop, not a target.
_SL_TO = re.compile(r"\b(sl|stop(?:\s?loss)?)\b[^\n.\d]{0,30}?\bto\s+(?=\d)", re.IGNORECASE)


def _community_symbol(text: str) -> str | None:
    """One coin the call is about; a list of several coins names no single symbol."""
    found = {match.group(1).upper() for pattern in (_TICKER_AFTER_DIRECTION, _TICKER_PAIR) for match in pattern.finditer(text)
             if match.group(1).lower() not in _NOT_TICKERS}
    return found.pop() if len(found) == 1 else None


def extract_call(message: GoatHubMessage, reference_price: Decimal | None = None) -> CommunityCall | None:
    """A call is a message that states a current direction; anything else is conversation."""
    if message.channel_role == ROLE_KNOWLEDGE or not message.content.strip():
        return None  # knowledge channels hold teaching material, not calls
    text = _SL_TO.sub(r"\1 at ", _SL_ON.sub(r"\1 at", _PERCENT.sub(" ", message.content)))
    guidance = parse_guidance(text, reference_price)
    if guidance.bias not in {"SHORT", "LONG"} or guidance.direction_withdrawn:
        return None
    coin_list = sum(1 for line in text.splitlines() if re.fullmatch(r"\s*\$?[A-Za-z][A-Za-z0-9]{1,9}\s*", line)) >= 3
    if coin_list:
        guidance = replace(guidance, symbol=None)  # a list of coins names no single symbol
    elif guidance.symbol is None:
        guidance = replace(guidance, symbol=_community_symbol(text))
    has_level = any(level.role != "STOP" for level in guidance.levels)
    has_stop = bool(guidance.invalidation) or any(level.role == "STOP" for level in guidance.levels)
    reasons = [f"Richtung {guidance.bias}"]
    if guidance.symbol:
        reasons.append(f"Symbol {guidance.symbol}")
    if has_level:
        reasons.append("Level genannt")
    if has_stop:
        reasons.append("Invalidierung/Stop genannt")
    if message.reactions >= POPULAR_REACTIONS:
        reasons.append(f"{message.reactions} Reaktionen")
    if guidance.symbol and has_level and has_stop:
        grade = "A"
    elif guidance.symbol and (has_level or has_stop):
        grade = "B"
    else:
        grade = "C"
    return CommunityCall(message, guidance, grade, tuple(reasons))


def good_calls(
    messages: Iterable[GoatHubMessage],
    *,
    observed_at: datetime | None = None,
    max_age: timedelta | None = None,
    reference_price: Decimal | None = None,
) -> list[CommunityCall]:
    """Good (grade A/B) calls known at ``observed_at``, newest first; never posts from after it."""
    calls = []
    for message in messages:
        if observed_at is not None and message.known_at > observed_at:
            continue
        if observed_at is not None and max_age is not None and observed_at - message.posted_at > max_age:
            continue
        call = extract_call(message, reference_price)
        if call is not None and call.is_good:
            calls.append(call)
    return sorted(calls, key=lambda item: (item.message.posted_at, item.message.message_id), reverse=True)


def _quote(text: str) -> list[str]:
    return ["> " + line if line.strip() else ">" for line in text.splitlines()] or [">"]


def _channel_title(message: GoatHubMessage) -> str:
    title = f"#{message.channel_name}" if message.channel_name else f"Kanal {message.channel_id}"
    return f"{title} (nur Wissen, keine Calls)" if message.channel_role == ROLE_KNOWLEDGE else title


def _call_line(call: CommunityCall) -> str:
    guidance = call.guidance
    levels = ", ".join(f"{level.role} {level.raw if level.ambiguous else level.value}" for level in guidance.levels) or "-"
    stop = "; ".join(guidance.invalidation) or "-"
    first = call.message.content.strip().splitlines()[0][:160]
    return (f"| {call.message.posted_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')} | {call.message.author_label} | {call.grade} | "
            f"{guidance.bias} {guidance.symbol or '?'}{' ' + guidance.timeframe if guidance.timeframe else ''} | {levels} | {stop} | "
            f"{first.replace('|', '/')} |")


def render_channel_markdown(messages: Sequence[GoatHubMessage], generated_at: datetime) -> str:
    """The whole channel, verbatim, grouped by channel and day, with the good calls on top."""
    calls = good_calls(messages)
    lines = [
        "# GoatHub-Kanal (vollständig)",
        "",
        f"Stand: {generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC. "
        f"{len(messages)} Nachrichten, {len(calls)} gute Calls (Note A/B).",
        "",
        "Alle Zeiten UTC. Community-Meinung, nur Beobachtung: kein Call ist eine Bestätigung oder ein Auftrag. "
        "Die Note sagt nur, wie vollständig ein Call geschrieben ist, nicht ob er stimmt.",
        "",
        "## Gute Calls",
        "",
    ]
    if calls:
        lines += ["| Zeit (UTC) | Autor | Note | Richtung | Level | Invalidierung | Text |", "| --- | --- | --- | --- | --- | --- | --- |"]
        lines += [_call_line(call) for call in calls]
    else:
        lines.append("Keine.")
    by_channel: dict[str, list[GoatHubMessage]] = defaultdict(list)
    for message in messages:
        by_channel[message.channel_id].append(message)
    for channel_messages in by_channel.values():
        lines += ["", f"## {_channel_title(channel_messages[0])}"]
        day = None
        for message in channel_messages:
            stamp = message.posted_at.astimezone(timezone.utc)
            if stamp.date() != day:
                day = stamp.date()
                lines += ["", f"### {day.isoformat()}"]
            extra = []
            if message.attachments:
                extra.append(f"{len(message.attachments)} Anhang/Anhänge: {', '.join(message.attachments)}")
            if message.reactions:
                extra.append(f"{message.reactions} Reaktionen")
            lines += ["", f"**{stamp.strftime('%H:%M')} {message.author_label}**" + (f" ({'; '.join(extra)})" if extra else "")]
            if message.content.strip():
                lines += _quote(message.content)
    return "\n".join(lines) + "\n"


def render_summary_markdown(messages: Sequence[GoatHubMessage], generated_at: datetime, full_path: str, limit_bytes: int = SUMMARY_LIMIT_BYTES) -> str:
    """Short version for a memory index (under 4 KB): counts, active authors and the newest good calls."""
    calls = good_calls(messages)
    authors: dict[str, int] = defaultdict(int)
    for message in messages:
        authors[message.author_label] += 1
    newest = messages[-1].posted_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M") if messages else "-"
    head = [
        "# GoatHub-Kanal (Kurzfassung)",
        "",
        f"Stand {generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC: {len(messages)} Nachrichten, "
        f"neueste {newest} UTC, {len(calls)} gute Calls. Volltext: {full_path}",
        "",
        "Aktivste Autoren: " + (", ".join(f"{name} ({count})" for name, count in sorted(authors.items(), key=lambda item: -item[1])[:8]) or "-"),
        "",
        "Neueste gute Calls (Community-Meinung, keine Bestätigung):",
    ]
    body: list[str] = []
    text = "\n".join(head) + "\n"
    for call in calls:
        guidance = call.guidance
        levels = ", ".join(level.raw if level.ambiguous else str(level.value) for level in guidance.levels) or "-"
        line = (f"- {call.message.posted_at.astimezone(timezone.utc).strftime('%m-%d %H:%M')} {call.message.author_label} [{call.grade}] "
                f"{guidance.bias} {guidance.symbol or '?'} Level {levels}: \"{call.message.content.strip().splitlines()[0][:100]}\"")
        if len((text + "\n".join(body + [line]) + "\n").encode("utf-8")) > limit_bytes:
            break
        body.append(line)
    return text + ("\n".join(body) if body else "- keine") + "\n"


def import_screen_readings(store: GoatHubFeedStore, payload: Sequence[dict[str, Any]], received_at: datetime | None = None) -> tuple[int, int]:
    """Store messages Claude read off the screen: [{channel_id, channel_name, author, posted_at, content}], idempotent by content hash."""
    received_at = received_at or datetime.now(timezone.utc)
    stored = duplicates = 0
    for item in payload:
        posted_at = datetime.fromisoformat(str(item["posted_at"]))
        if posted_at.tzinfo is None:
            raise ValueError("posted_at must carry a time zone")
        posted_at = posted_at.astimezone(timezone.utc)
        channel_id = str(item.get("channel_id") or "screen")
        author = str(item.get("author") or "")
        content = str(item.get("content") or "")
        digest = hashlib.sha256(f"{channel_id}|{author}|{posted_at.isoformat()}|{content}".encode()).hexdigest()[:20]
        message = GoatHubMessage(
            message_id=f"screen-{digest}", channel_id=channel_id, posted_at=posted_at, content=content,
            received_at=received_at, author_name=author, channel_name=str(item.get("channel_name") or ""),
            source=SOURCE_SCREEN, attachments=tuple(str(name) for name in item.get("attachments") or ()),
            reactions=int(item.get("reactions") or 0),
        )
        if store.append(message):
            stored += 1
        else:
            duplicates += 1
    return stored, duplicates


def write_memory_export(store: GoatHubFeedStore, out_dirs: Sequence[Path], generated_at: datetime | None = None) -> list[Path]:
    """Write GOATHUB_KANAL.md, GOATHUB_KURZ.md and goathub_calls.json into each directory (atomic replace)."""
    generated_at = generated_at or datetime.now(timezone.utc)
    messages = store.load()
    calls = good_calls(messages)
    written: list[Path] = []
    for out_dir in out_dirs:
        out_dir = out_dir.expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        full = out_dir / "GOATHUB_KANAL.md"
        files = {
            full: render_channel_markdown(messages, generated_at),
            out_dir / "GOATHUB_KURZ.md": render_summary_markdown(messages, generated_at, str(full)),
            out_dir / "goathub_calls.json": json.dumps(
                {"generated_at": generated_at.isoformat(), "messages": len(messages), "calls": [call.to_dict() for call in calls]},
                ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        }
        for path, content in files.items():
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(content, encoding="utf-8")
            os.replace(temporary, path)
            written.append(path)
    return written
