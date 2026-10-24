"""GoatHub community calls next to TIM's own analysis (display only).

TIM treats the GoatHub community as HUMAN_COMMUNITY_TRADING_RESEARCH: human trading research
that is read as a hypothesis with author, time and evidence.

Good calls (grade A/B, see ``src/knowledge/goathub_feed.py``) for the analysed
symbol are listed with their levels checked against the candles and their
numeric invalidation checked by close. Unlike Broncx guidance they do not
weight scores and add no scenarios: community authors have no track record in
TIM yet. They never count as confirmation and never change the decision.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Sequence

from src.knowledge.goathub_feed import GoatHubMessage, good_calls
from src.models.market_data import Candle

from .external_context import _base, _invalidation_check, _level_check, _reference, _since

__all__ = ["COMMUNITY_CALLS_RULE", "DEFAULT_CALL_MAX_AGE", "SOURCE_CLASS", "build_community_calls"]

# How TIM classifies the GoatHub community: people sharing trading research, i.e. hypotheses
# with author, time and evidence, never confirmation.
SOURCE_CLASS = "HUMAN_COMMUNITY_TRADING_RESEARCH"

DEFAULT_CALL_MAX_AGE = timedelta(hours=24)
COMMUNITY_CALLS_RULE = (
    "GoatHub community calls are shown for review only: they do not change scores, scenarios, "
    "confirmations or the decision, and calls posted or received after the analysis time are not used."
)


def _hours(delta: timedelta) -> float:
    return round(delta.total_seconds() / 3600, 1)


def build_community_calls(
    messages: Sequence[GoatHubMessage],
    *,
    observed_at: datetime,
    symbol: str,
    candles: Sequence[Candle],
    price_now: Decimal | None,
    max_age: timedelta = DEFAULT_CALL_MAX_AGE,
    limit: int = 5,
) -> dict[str, Any]:
    reference = _reference(candles, price_now)
    base = _base(symbol)
    calls = [call for call in good_calls(messages, observed_at=observed_at, max_age=max_age, reference_price=reference) if call.guidance.symbol == base]
    entries = []
    for call in calls[:limit]:
        since = _since(candles, call.message.posted_at)
        entries.append({
            "message_id": call.message.message_id,
            "channel": call.message.channel_name or call.message.channel_id,
            "author": call.message.author_label,
            "age_hours": _hours(observed_at - call.message.posted_at),
            "grade": call.grade,
            "reasons": list(call.reasons),
            "bias": call.guidance.bias,
            "symbol": call.guidance.symbol,
            "timeframe": call.guidance.timeframe,
            "reactions": call.message.reactions,
            "text": call.message.content,
            "levels": [_level_check(level.value, level.role, reference, since) for level in call.guidance.levels if not level.ambiguous],
            "invalidation": [_invalidation_check(item, reference, since) for item in call.guidance.invalidation],
        })
    return {
        "rule": COMMUNITY_CALLS_RULE,
        "source_class": SOURCE_CLASS,
        "influences_scores": False,
        "max_age_hours": _hours(max_age),
        "calls_found": len(calls),
        "entries": entries,
    }
