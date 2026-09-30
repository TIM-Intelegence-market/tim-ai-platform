"""Broncx Discord feed: stored posts and a heuristic guidance parser.

Posts arrive from the TIM owner's own Discord server, where Broncx messages are
forwarded (one click on "Forward") into a dedicated channel and picked up by
``src/sources/broncx_discord.py``. This module only stores and parses them.

Status: external opinion, observation-only. A parsed post is guidance for TIM
(a hypothesis, levels to check, an invalidation to watch); it is never market
evidence, never a confirmation and never an instruction. The raw text is kept
verbatim so every parsed field can be checked against what Broncx wrote.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "BroncxFeedStore",
    "BroncxGuidance",
    "BroncxLevel",
    "BroncxPost",
    "default_feed_dir",
    "parse_guidance",
]

SOURCE_FORWARD = "discord_forward"
SOURCE_MANUAL = "discord_manual"

_SYMBOLS = {"btc": "BTC", "bitcoin": "BTC", "eth": "ETH", "ether": "ETH", "sol": "SOL", "xau": "XAU", "gold": "XAU"}
# Phrases whose direction word means the opposite ("short squeeze" is bullish), removed before bias detection.
_REVERSED = re.compile(r"\bshorts?\s+squeez\w*|\bsqueez\w*\s+(?:the\s+)?shorts?\b|\b(?:shorts?|longs?)\s+(?:(?:got|get|getting|are|were|being)\s+)?(?:liquidated|trapped|squeezed|rekt|stopped out)\b", re.IGNORECASE)
# Negated or closed positions ("not shorting", "no longs", "closed my short") state no current direction.
_NEGATED = re.compile(
    r"\b(?:not|no|never|don'?t|won'?t|avoid(?:ing)?)\s+(?:\w+\s+){0,2}?(?:shorts?|shorting|longs?|longing|buy(?:ing)?|sell(?:ing)?)\b"
    r"|\b(?:clos(?:ed?|ing)|exit(?:ed|ing)?|out\s+of|cut)\s+(?:my\s+|the\s+|all\s+)?(?:shorts?|longs?)\b",
    re.IGNORECASE,
)
_SHORT = re.compile(r"\b(shorts?|shorting|bearish|sell(?:ing)?)\b", re.IGNORECASE)
_LONG = re.compile(r"\b(longs?|longing|bullish|buy(?:ing)?)\b", re.IGNORECASE)
_SYMBOL_TF = re.compile(r"\b(btc|bitcoin|eth|ether|sol|xau|gold)\b(?:\s+(\d{1,3})\s*(m|min|h)?\b)?", re.IGNORECASE)
# Only common chart timeframes, so "btc 83" stays a price and does not become "83m".
_MINUTES = {1, 3, 5, 15, 30, 45, 60, 120, 240}
_HOURS = {1, 2, 4, 6, 8, 12}
# A number not glued to letters or digits on either side ("tp1" and "0x12" are not levels).
_NUMBER = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(\s?k)?(?!\w|,\d|%|\.\d|\s%)", re.IGNORECASE)
_TARGET_CONTEXT = re.compile(r"\b(tp\s?\d?|targets?(?:\s?\d)?|towards?|to)\s*(?:at|@|:)?\s*$", re.IGNORECASE)
# His stop or invalidation price: never an entry level.
_STOP_CONTEXT = re.compile(r"\b(sl|stop(?:\s?loss)?|stopped)\s*(?:at|@|:)?\s*$", re.IGNORECASE)
# End of a clause: punctuation, but not the "," or "." inside a number such as 83,000 or 82.6.
_END = r"[,.](?!\d)|[;!?\n]|$"
_UNLESS = re.compile(r"\bunless\s+(.+?)(?=\s+(?:shorts?|longs?|then)\b|" + _END + ")", re.IGNORECASE)
_INVALID = re.compile(r"\binvalid(?:ated|ation)?\s+((?:if|on|above|below)\s+.+?)(?=" + _END + ")", re.IGNORECASE)
_IF = re.compile(r"\bif\s+(.+?)(?=\s+(?:take|then|go|enter)\b|" + _END + ")", re.IGNORECASE)
_REFERENCES = {
    "POC": r"\bv?poc\b",
    "VAH": r"\bvah\b",
    "VAL": r"\bval\b",
    "VWAP": r"\bvwap\b",
    "FVG": r"\bfvg\b",
    "ORDER_BLOCK": r"\b(?:ob|order ?block)\b",
    "RANGE": r"\brange\b",
    "LOW": r"\blows?\b",
    "HIGH": r"\bhighs?\b",
    "REJECTION": r"\breject(?:ion|ed)?\b",
    "BREAK": r"\bbreak(?:s|out)?\b",
}
# A shorthand like "82.6" is read as 82,600 only when that lies within +-30 % of the current price.
_PLAUSIBLE_LOW, _PLAUSIBLE_HIGH = Decimal("0.7"), Decimal("1.3")
_REAFFIRM = re.compile(r"\b(play(?:s|ing)? out again|still valid|same (?:idea|plan)|as planned|still in)\b", re.IGNORECASE)


def default_feed_dir() -> Path:
    """Local, untracked feed directory (``data/`` is git-ignored)."""
    override = os.environ.get("TIM_BRONCX_FEED_DIR")
    if override:
        return Path(override).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "broncx_feed"


@dataclass(frozen=True, slots=True)
class BroncxPost:
    message_id: str
    posted_at: datetime
    content: str
    received_at: datetime
    source: str = SOURCE_FORWARD
    attachments: tuple[str, ...] = ()
    forwarded_by: str = ""
    note: str = ""
    # Cached chart readings (``broncx_chart_vision.ChartReading``) attached by ``BroncxFeedStore.load``;
    # never written to posts.jsonl.
    chart_readings: tuple[Any, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        if not self.message_id:
            raise ValueError("message_id is required")
        if self.posted_at.tzinfo is None or self.received_at.tzinfo is None:
            raise ValueError("post timestamps must be timezone-aware")
        if not self.content.strip() and not self.attachments:
            raise ValueError("post has neither text nor attachments")

    @property
    def known_at(self) -> datetime:
        """When TIM could first know the post: posted, and also received by the bot."""
        return max(self.posted_at, self.received_at)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["posted_at"] = self.posted_at.isoformat()
        payload["received_at"] = self.received_at.isoformat()
        payload["attachments"] = list(self.attachments)
        payload.pop("chart_readings", None)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BroncxPost":
        return cls(
            message_id=str(payload["message_id"]),
            posted_at=datetime.fromisoformat(payload["posted_at"]),
            content=str(payload.get("content", "")),
            received_at=datetime.fromisoformat(payload["received_at"]),
            source=str(payload.get("source", SOURCE_FORWARD)),
            attachments=tuple(str(item) for item in payload.get("attachments", ())),
            forwarded_by=str(payload.get("forwarded_by", "")),
            note=str(payload.get("note", "")),
        )


class BroncxFeedStore:
    """Append-only JSONL store, idempotent by Discord message id."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or default_feed_dir()
        self.posts_path = self.root / "posts.jsonl"
        self.state_path = self.root / "state.json"

    def load(self) -> list[BroncxPost]:
        if not self.posts_path.exists():
            return []
        posts: dict[str, BroncxPost] = {}
        for line in self.posts_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                post = BroncxPost.from_dict(json.loads(line))
            except (ValueError, KeyError, TypeError):
                continue  # a torn last line after a crash must not hide the other posts
            posts.setdefault(post.message_id, post)
        return sorted(self._with_chart_readings(posts.values()), key=lambda item: (item.posted_at, item.message_id))

    def _with_chart_readings(self, posts: Iterable[BroncxPost]) -> list[BroncxPost]:
        from .broncx_chart_vision import ChartImageStore  # local import: the vision module builds on this one

        images = ChartImageStore(self.root)
        readings = images.readings()
        if not readings:
            return list(posts)
        return [replace(post, chart_readings=tuple(images.readings_for(post.message_id, readings))) for post in posts]

    def append(self, post: BroncxPost) -> bool:
        if any(existing.message_id == post.message_id for existing in self.load()):
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        torn = self.posts_path.exists() and self.posts_path.stat().st_size > 0 and not self.posts_path.read_bytes().endswith(b"\n")
        with self.posts_path.open("a", encoding="utf-8") as stream:
            if torn:
                stream.write("\n")
            stream.write(json.dumps(post.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return True

    def last_message_id(self) -> str | None:
        try:
            value = json.loads(self.state_path.read_text(encoding="utf-8")).get("last_message_id")
        except (OSError, ValueError, AttributeError):
            return None
        return str(value) if value else None

    def set_last_message_id(self, message_id: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"last_message_id": message_id}), encoding="utf-8")
        os.replace(temporary, self.state_path)

    def posts_until(self, observed_at: datetime) -> list[BroncxPost]:
        """Posts TIM already had at ``observed_at`` (no lookahead in replays)."""
        return [post for post in self.load() if post.known_at <= observed_at]


@dataclass(frozen=True, slots=True)
class BroncxLevel:
    raw: str
    value: Decimal
    role: str  # TARGET | STOP | LEVEL, and ENTRY for a position tool read from a chart
    scaled_from_shorthand: bool = False
    ambiguous: bool = False
    source: str = "text"  # text | chart (read from an image by the local vision model, estimated)

    def to_dict(self) -> dict[str, Any]:
        return {"raw": self.raw, "value": str(self.value), "role": self.role, "scaled_from_shorthand": self.scaled_from_shorthand, "ambiguous": self.ambiguous, "source": self.source}


@dataclass(frozen=True, slots=True)
class BroncxGuidance:
    bias: str  # SHORT | LONG | MIXED | NONE
    symbol: str | None
    timeframe: str | None
    levels: tuple[BroncxLevel, ...]
    invalidation: tuple[str, ...]
    conditions: tuple[str, ...]
    references: tuple[str, ...]
    reaffirms_previous: bool
    parse_quality: str  # STRUCTURED | PARTIAL | UNSTRUCTURED
    notes: tuple[str, ...] = field(default=())
    chart_readings: int = 0  # chart images whose reading was merged in
    direction_withdrawn: bool = False  # "closed my short", "no longs", "shorts got squeezed"
    bias_source: str = "text"  # text | chart (image-only post) | chart_text_silent (text names no direction)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bias": self.bias,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "levels": [level.to_dict() for level in self.levels],
            "invalidation": list(self.invalidation),
            "conditions": list(self.conditions),
            "references": list(self.references),
            "reaffirms_previous": self.reaffirms_previous,
            "parse_quality": self.parse_quality,
            "notes": list(self.notes),
            "chart_readings": self.chart_readings,
            "direction_withdrawn": self.direction_withdrawn,
            "bias_source": self.bias_source,
        }


def parse_guidance(text: str, reference_price: Decimal | None = None) -> BroncxGuidance:
    """Best-effort structure from a Broncx post. Unrecognised text stays raw, never guessed."""
    notes: list[str] = []
    withdrawn = False
    directional = _REVERSED.sub(" ", text)
    if directional != text:
        notes.append("squeeze/liquidation wording ignored for bias")
        withdrawn = True
    negated = _NEGATED.sub(" ", directional)
    if negated != directional:
        notes.append("negated or closed position ignored for bias")
        directional = negated
        withdrawn = True
    short, long = bool(_SHORT.search(directional)), bool(_LONG.search(directional))
    bias = "MIXED" if short and long else "SHORT" if short else "LONG" if long else "NONE"

    symbol = timeframe = None
    timeframe_span: tuple[int, int] | None = None
    match = _SYMBOL_TF.search(text)
    if match:
        symbol = _SYMBOLS[match.group(1).lower()]
        if match.group(2):
            amount = int(match.group(2))
            unit = (match.group(3) or "m").lower()
            if unit == "h" and amount in _HOURS:
                timeframe = f"{amount}h"
            elif unit != "h" and amount in _MINUTES:
                timeframe = f"{amount}m"
            if timeframe:
                timeframe_span = match.span(2)

    invalidation_matches = [item for pattern in (_UNLESS, _INVALID) for item in pattern.finditer(text)]
    stop_spans = [item.span(1) for item in invalidation_matches]
    levels: list[BroncxLevel] = []
    for number in _NUMBER.finditer(text):
        if timeframe_span and number.span(1) == timeframe_span:
            continue
        in_invalidation = any(start <= number.start() < end for start, end in stop_spans)
        level = _level(number, text, reference_price, stop=in_invalidation)
        if level is None:
            continue
        levels.append(level)
        if level.ambiguous:
            notes.append(f"level {level.raw} could not be scaled without a reference price")

    invalidation = tuple(item.group(1).strip() for item in invalidation_matches)
    conditions = tuple(item.group(1).strip() for item in _IF.finditer(text))
    references = tuple(name for name, pattern in _REFERENCES.items() if re.search(pattern, text, re.IGNORECASE))
    reaffirms = bool(_REAFFIRM.search(text))

    if bias in {"SHORT", "LONG"} and (levels or invalidation):
        quality = "STRUCTURED"
    elif bias != "NONE" or levels or invalidation or conditions or reaffirms:
        quality = "PARTIAL"
    else:
        quality = "UNSTRUCTURED"
    return BroncxGuidance(bias, symbol, timeframe, tuple(levels), invalidation, conditions, references, reaffirms, quality, tuple(notes),
                          direction_withdrawn=withdrawn)


def _level(number: re.Match[str], text: str, reference_price: Decimal | None, *, stop: bool = False) -> BroncxLevel | None:
    raw = number.group(0).strip()
    try:
        value = Decimal(number.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    if value <= 0:
        return None
    scaled = ambiguous = False
    if number.group(2):
        value *= 1000
        scaled = True
        if reference_price is not None and reference_price > 0 and not _PLAUSIBLE_LOW <= value / reference_price <= _PLAUSIBLE_HIGH:
            return None  # "1.5k profit" is an amount, not a price level
    elif value < 1000:
        if reference_price is not None and reference_price > 0:
            candidate = value * 1000
            if _PLAUSIBLE_LOW <= candidate / reference_price <= _PLAUSIBLE_HIGH:
                value, scaled = candidate, True
            elif not _PLAUSIBLE_LOW <= value / reference_price <= _PLAUSIBLE_HIGH:
                return None  # neither a price nor a shorthand price: a count, a percent, a size
        else:
            ambiguous = True
    if scaled and value == value.to_integral_value():
        value = value.quantize(Decimal(1))
    before = text[: number.start()]
    role = "STOP" if stop or _STOP_CONTEXT.search(before) else "TARGET" if _TARGET_CONTEXT.search(before) else "LEVEL"
    return BroncxLevel(raw, value, role, scaled, ambiguous)


def iter_recent(posts: Iterable[BroncxPost], observed_at: datetime, max_age: timedelta) -> list[BroncxPost]:
    return [post for post in posts if timedelta(0) <= observed_at - post.posted_at <= max_age]
