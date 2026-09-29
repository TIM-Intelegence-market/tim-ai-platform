"""External guidance context: Broncx's current view next to TIM's own analysis.

Broncx posts (forwarded from Discord, see ``src/knowledge/broncx_feed.py``) are
used as guidance: they name a bias, levels to check and an invalidation to
watch, and TIM reports whether its own evidence agrees. They are recorded in
the audit and the report only. They never enter the data-quality gate, the
scenario scores, the confirmations, the trade plan or the decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from src.knowledge.broncx_feed import BroncxGuidance, BroncxPost, parse_guidance
from src.models.market_data import Candle

from .domain import ConfirmationState, Direction, Scenario

__all__ = ["DEFAULT_MAX_AGE", "EXTERNAL_CONTEXT_RULE", "build_external_context"]

DEFAULT_MAX_AGE = timedelta(hours=24)
# Consecutive posts this close together form one thought ("Fc btc 15" then "tp2 at 82.6").
THREAD_WINDOW = timedelta(minutes=30)
# "This might play out again" only renews a directional view from the last seven days.
RENEW_WINDOW = timedelta(days=7)
EXTERNAL_CONTEXT_RULE = (
    "Broncx guidance is external opinion: it may raise hypotheses and name levels to check, "
    "it never counts as confirmation, never changes scores, scenarios or the decision, "
    "and is no longer used once older than max_age."
)
_THRESHOLD = re.compile(r"\b(above|below)\b", re.IGNORECASE)


@dataclass(slots=True)
class _Entry:
    post: BroncxPost
    guidance: BroncxGuidance
    symbol: str | None
    timeframe: str | None
    symbol_inherited: bool = False
    renewed_at: datetime | None = None
    renews: str | None = None

    @property
    def effective_at(self) -> datetime:
        return max(self.post.posted_at, self.renewed_at or self.post.posted_at)


def build_external_context(
    posts: Sequence[BroncxPost],
    *,
    observed_at: datetime,
    symbol: str,
    candles: Sequence[Candle],
    price_now: Decimal | None,
    scenarios: Sequence[Scenario],
    max_age: timedelta = DEFAULT_MAX_AGE,
    limit: int = 5,
) -> dict[str, Any]:
    known = sorted((post for post in posts if post.known_at <= observed_at), key=lambda item: (item.posted_at, item.message_id))
    reference = price_now if price_now is not None else (Decimal(str(candles[-1].close)) if candles else None)
    entries = _thread(known, reference)
    tim_directions = {item.direction for item in scenarios if item.state not in {ConfirmationState.INVALIDATED, ConfirmationState.EXPIRED} and item.direction != Direction.NEUTRAL}

    def status_of(entry: _Entry) -> str:
        if entry.symbol and not symbol.upper().startswith(entry.symbol):
            return "OTHER_SYMBOL"
        return "ACTIVE" if observed_at - entry.effective_at <= max_age else "STALE"

    # Every active entry is shown; the limit only trims stale and other-symbol history.
    newest_first = list(reversed(entries))
    active = [entry for entry in newest_first if status_of(entry) == "ACTIVE"]
    selected = {id(entry) for entry in active} | {id(entry) for entry in [item for item in newest_first if status_of(item) != "ACTIVE"][: max(limit - len(active), 0)]}

    rendered = []
    for entry in (item for item in newest_first if id(item) in selected):
        status = status_of(entry)
        item: dict[str, Any] = {
            "message_id": entry.post.message_id,
            "posted_at": entry.post.posted_at.isoformat(),
            "age_hours": _hours(observed_at - entry.post.posted_at),
            "status": status,
            "text": entry.post.content,
            "note": entry.post.note,
            "attachments": len(entry.post.attachments),
            "source": entry.post.source,
            "symbol": entry.symbol,
            "symbol_inherited": entry.symbol_inherited,
            "timeframe": entry.timeframe,
            "renewed_at": entry.renewed_at.isoformat() if entry.renewed_at else None,
            "renews": entry.renews,
            "guidance": entry.guidance.to_dict(),
        }
        if status == "ACTIVE":
            # Only candles that opened after the post: a wick from before the post is no reaction to it.
            since = [candle for candle in candles if candle.open_time >= entry.post.posted_at]
            item["level_checks"] = [_level_check(level.value, level.role, reference, since) for level in entry.guidance.levels if not level.ambiguous]
            item["invalidation_checks"] = [_invalidation_check(text, reference, since) for text in entry.guidance.invalidation]
            item["alignment"] = _alignment(entry.guidance.bias, tim_directions, bool(scenarios))
        rendered.append(item)

    return {
        "source": "broncx_discord",
        "rule": EXTERNAL_CONTEXT_RULE,
        "influences_decision": False,
        "max_age_hours": _hours(max_age),
        "posts_known": len(known),
        "posts_excluded_future": len(posts) - len(known),
        "tim_directions": sorted(direction.value for direction in tim_directions),
        "entries": rendered,
    }


def _thread(posts: Sequence[BroncxPost], reference: Decimal | None) -> list[_Entry]:
    entries: list[_Entry] = []
    for post in posts:
        guidance = parse_guidance(post.content, reference)
        entry = _Entry(post, guidance, guidance.symbol, guidance.timeframe)
        previous = entries[-1] if entries else None
        if entry.symbol is None and previous and post.posted_at - previous.post.posted_at <= THREAD_WINDOW and previous.symbol:
            entry.symbol, entry.timeframe, entry.symbol_inherited = previous.symbol, previous.timeframe, True
        if guidance.reaffirms_previous and guidance.bias == "NONE":
            # "This might play out again" renews the latest directional view instead of standing alone.
            target = next((item for item in reversed(entries) if item.guidance.bias in {"SHORT", "LONG"} and post.posted_at - item.post.posted_at <= RENEW_WINDOW), None)
            if target is not None:
                target.renewed_at = post.posted_at
                entry.renews = target.post.message_id
                entry.symbol = entry.symbol or target.symbol
        entries.append(entry)
    return entries


def _level_check(value: Decimal, role: str, reference: Decimal | None, since: Sequence[Candle]) -> dict[str, Any]:
    if not since:
        reached = "NO_DATA_SINCE_POST"
    elif any(Decimal(str(candle.low)) <= value <= Decimal(str(candle.high)) for candle in since):
        reached = "TOUCHED"
    else:
        reached = "NOT_REACHED"
    distance = None if not reference else str(((value - reference) / reference * 100).quantize(Decimal("0.01")))
    return {"level": str(value), "role": role, "status": reached, "distance_pct": distance}


def _invalidation_check(text: str, reference: Decimal | None, since: Sequence[Candle]) -> dict[str, Any]:
    side = _THRESHOLD.search(text)
    levels = [level for level in parse_guidance(text, reference).levels if not level.ambiguous]
    if not side or not levels:
        return {"text": text, "status": "NOT_EVALUATED", "reason": "no numeric threshold; check manually"}
    level = levels[0].value
    if not since:
        return {"text": text, "level": str(level), "status": "NO_DATA_SINCE_POST"}
    closes = [Decimal(str(candle.close)) for candle in since]
    # Acceptance, not a wick: a close beyond the threshold is what invalidates.
    hit = any(close > level for close in closes) if side.group(1).lower() == "above" else any(close < level for close in closes)
    return {"text": text, "level": str(level), "status": "TRIGGERED" if hit else "NOT_TRIGGERED"}


def _alignment(bias: str, tim_directions: set[Direction], has_scenarios: bool) -> str:
    if bias not in {"SHORT", "LONG"}:
        return "NO_BIAS"
    if not has_scenarios or not tim_directions:
        return "UNTESTED"
    same = Direction(bias) in tim_directions
    opposite = Direction("LONG" if bias == "SHORT" else "SHORT") in tim_directions
    if same and opposite:
        return "PARTIAL"
    return "ALIGNED" if same else "CONFLICT"


def _hours(delta: timedelta) -> float:
    return round(delta.total_seconds() / 3600, 2)
