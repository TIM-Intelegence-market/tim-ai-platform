"""Deterministic parsing of OpenMarket ``GET /v1/points`` candle responses.

Verified (owner-checked documentation, 2026-09-29): candle point fields
``open high low close volume timestamp firstTimestamp lastTimestamp`` for
``TRADE_SIDE_AGNOSTIC_AGG``; ``TRADE_AGG`` returns separate BUY and SELL series.

NOT verified: the JSON envelope around the points, where the BUY/SELL side is
carried in a ``TRADE_AGG`` response, and the timestamp encoding of REST points.
The parser therefore does not assume envelope key names. It finds the point
lists by their documented fields, reads the side from the nearest enclosing
object (``side`` or ``series.side``, as documented for WebSocket series), and
accepts only unambiguous timestamp encodings. Anything else is a
``SCHEMA_MISMATCH``; nothing is guessed or filled in.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .errors import OpenMarketError, OpenMarketErrorKind

CANDLE_REQUIRED = ("open", "high", "low", "close", "volume", "timestamp")
CANDLE_OPTIONAL = ("firstTimestamp", "lastTimestamp")
CANDLE_FIELDS = frozenset(CANDLE_REQUIRED + CANDLE_OPTIONAL)
SIDES = frozenset({"BUY", "SELL"})

# Documented REST interval names and their length.
INTERVAL_SECONDS = {
    "MINUTE": 60,
    "FIVE_MINUTES": 300,
    "FIFTEEN_MINUTES": 900,
    "THIRTY_MINUTES": 1_800,
    "HOUR": 3_600,
    "FOUR_HOURS": 14_400,
    "DAY": 86_400,
    "WEEK": 604_800,
}
# Epoch seconds larger than this are milliseconds or finer: ambiguous, rejected.
_MAX_EPOCH_SECONDS = 100_000_000_000
_MAX_DEPTH = 8


def _mismatch(message: str) -> OpenMarketError:
    return OpenMarketError(OpenMarketErrorKind.SCHEMA_MISMATCH, message)


def parse_json(body: bytes) -> Any:
    """JSON with exact decimals: floats never pass through binary floating point."""
    try:
        return json.loads(body.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _mismatch("response is not valid JSON") from None


def to_decimal(value: Any, *, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise _mismatch(f"{label} is not numeric")
    if isinstance(value, float):
        # Only reachable if a caller bypassed parse_json; keep the shortest repr.
        value = repr(value)
    try:
        result = Decimal(str(value)) if not isinstance(value, Decimal) else value
    except (InvalidOperation, ValueError):
        raise _mismatch(f"{label} is not numeric") from None
    if not result.is_finite():
        raise _mismatch(f"{label} is not finite")
    return result


def to_timestamp_ns(value: Any, *, label: str) -> int:
    """UTC epoch nanoseconds from a documented-safe encoding.

    Accepted: ``{"seconds": s, "nanoseconds": n}`` (documented for WebSocket
    trades), integer epoch seconds (the unit of the documented ``from``
    parameter), or an ISO-8601 string with an explicit offset.
    """
    if isinstance(value, dict):
        seconds, nanos = value.get("seconds"), value.get("nanoseconds", 0)
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not isinstance(nanos, int) or isinstance(nanos, bool):
            raise _mismatch(f"{label} seconds/nanoseconds must be integers")
        if not 0 <= nanos < 1_000_000_000:
            raise _mismatch(f"{label} nanoseconds out of range")
        return seconds * 1_000_000_000 + nanos
    if isinstance(value, int) and not isinstance(value, bool):
        if not 0 <= value < _MAX_EPOCH_SECONDS:
            raise _mismatch(f"{label} integer is not epoch seconds (ambiguous unit)")
        return value * 1_000_000_000
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise _mismatch(f"{label} is not ISO-8601") from None
        if parsed.tzinfo is None:
            raise _mismatch(f"{label} has no timezone")
        parsed = parsed.astimezone(timezone.utc)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        delta = parsed - epoch
        return (delta.days * 86_400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1_000
    raise _mismatch(f"{label} has an unsupported timestamp encoding")


def ns_to_datetime(value: int) -> datetime:
    """UTC datetime (microsecond resolution; the exact value stays in ``*_ns``)."""
    return datetime.fromtimestamp(value // 1_000_000_000, tz=timezone.utc).replace(
        microsecond=(value % 1_000_000_000) // 1_000
    )


@dataclass(frozen=True, slots=True)
class CandlePoint:
    side: str | None  # None for TRADE_SIDE_AGNOSTIC_AGG
    timestamp_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    first_timestamp_ns: int | None = None
    last_timestamp_ns: int | None = None

    @property
    def timestamp(self) -> datetime:
        return ns_to_datetime(self.timestamp_ns)


@dataclass(slots=True)
class ParsedSeries:
    points: list[CandlePoint] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    unexpected_fields: set[str] = field(default_factory=set)
    envelope_paths: list[str] = field(default_factory=list)


def _is_point_list(node: Any) -> bool:
    return (
        isinstance(node, list)
        and bool(node)
        and all(isinstance(item, dict) for item in node)
        and any("timestamp" in item and "close" in item for item in node)
    )


def _side_of(node: dict[str, Any]) -> str | None:
    side = node.get("side")
    if side is None and isinstance(node.get("series"), dict):
        side = node["series"].get("side")
    return side if isinstance(side, str) else None


def _walk(node: Any, path: str, side: str | None, depth: int, found: list[tuple[str, str | None, list]]) -> None:
    if depth > _MAX_DEPTH:
        return
    if _is_point_list(node):
        found.append((path, side, node))
        return
    if isinstance(node, dict):
        own = _side_of(node)
        for key, value in node.items():
            _walk(value, f"{path}.{key}", own or side, depth + 1, found)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk(value, f"{path}[{index}]", side, depth + 1, found)


def parse_candles(payload: Any, *, per_side: bool) -> ParsedSeries:
    found: list[tuple[str, str | None, list]] = []
    _walk(payload, "$", None, 0, found)
    if not found:
        raise _mismatch("no candle point list with documented fields found")
    if not per_side and len(found) != 1:
        raise _mismatch("side-agnostic response contains more than one point list (ambiguous)")
    if per_side:
        sides = [side for _, side, _ in found]
        if any(side not in SIDES for side in sides):
            raise _mismatch("per-side response has a point list without a BUY/SELL side")
        if len(set(sides)) != len(sides):
            raise _mismatch("per-side response repeats a side (ambiguous)")
    result = ParsedSeries()
    for path, side, items in found:
        result.envelope_paths.append(path)
        for index, item in enumerate(items):
            label = f"{path}[{index}]"
            result.unexpected_fields.update(set(item) - CANDLE_FIELDS)
            missing = [name for name in CANDLE_REQUIRED if item.get(name) is None]
            if missing:
                result.rejected.append(f"{label}: missing {','.join(missing)}")
                continue
            try:
                point = CandlePoint(
                    side=side if per_side else None,
                    timestamp_ns=to_timestamp_ns(item["timestamp"], label=f"{label}.timestamp"),
                    open=to_decimal(item["open"], label=f"{label}.open"),
                    high=to_decimal(item["high"], label=f"{label}.high"),
                    low=to_decimal(item["low"], label=f"{label}.low"),
                    close=to_decimal(item["close"], label=f"{label}.close"),
                    volume=to_decimal(item["volume"], label=f"{label}.volume"),
                    first_timestamp_ns=(
                        to_timestamp_ns(item["firstTimestamp"], label=f"{label}.firstTimestamp")
                        if item.get("firstTimestamp") is not None else None
                    ),
                    last_timestamp_ns=(
                        to_timestamp_ns(item["lastTimestamp"], label=f"{label}.lastTimestamp")
                        if item.get("lastTimestamp") is not None else None
                    ),
                )
            except OpenMarketError as error:
                result.rejected.append(f"{label}: {error}")
                continue
            if point.low > min(point.open, point.close) or point.high < max(point.open, point.close) or point.volume < 0:
                result.rejected.append(f"{label}: invalid OHLC/volume relationship")
                continue
            result.points.append(point)
    return result
