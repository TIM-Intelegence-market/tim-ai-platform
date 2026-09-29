"""Deterministic parsing of OpenMarket ``GET /v1/points`` candle responses.

Documented REST schema (owner-verified official docs, 2026-09-29) - the
primary, strict path:

    {"series": [{"id": {"type", "exchange", "rawSymbol", "normalizedSymbol",
                        "category", "interval", "coin", ["side"]},
                 "points": [{"Point": {"open", "high", "low", "close", "volume",
                                       "timestamp": {"s"[, "ns"]},
                                       "firstTimestamp": {"s", "ns"},
                                       "lastTimestamp": {"s", "ns"}}}]}]}

- ``TRADE_AGG`` carries BUY/SELL in ``series[].id.side``.
- REST timestamps are ``{"s"[, "ns"]}``; the WebSocket schema
  ``{"seconds"[, "nanoseconds"]}`` is a different, separately supported shape.
  The two are never mixed.
- Any deviation on the documented path is a ``SCHEMA_MISMATCH``.

A structural fallback (point lists found by their fields) remains for
non-documented shapes. Its result is marked ``documented_envelope=False`` and
the proof never accepts it as provider evidence. Nothing is guessed or filled in.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

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
_MAX_DECIMAL_EXPONENT = 30  # anything larger is not a plausible price/volume
_MAX_DEPTH = 8


def _mismatch(message: str) -> OpenMarketError:
    return OpenMarketError(OpenMarketErrorKind.SCHEMA_MISMATCH, message)


def parse_json(body: bytes) -> Any:
    """JSON with exact decimals: floats never pass through binary floating point."""
    try:
        return json.loads(body.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, ValueError, RecursionError):  # JSONDecodeError is a ValueError
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
    if not result.is_finite() or result.adjusted() > _MAX_DECIMAL_EXPONENT:
        raise _mismatch(f"{label} is not a finite plausible number")
    return result


REST_TIMESTAMP_KEYS = (frozenset({"s"}), frozenset({"s", "ns"}))
WEBSOCKET_TIMESTAMP_KEYS = (frozenset({"seconds"}), frozenset({"seconds", "nanoseconds"}))


def timestamp_encoding(value: Any) -> str:
    """REST ``{s[,ns]}``, WEBSOCKET ``{seconds[,nanoseconds]}``, EPOCH_SECONDS, ISO8601 or UNKNOWN."""
    if isinstance(value, dict):
        keys = frozenset(value)
        if keys in REST_TIMESTAMP_KEYS:
            return "REST"
        if keys in WEBSOCKET_TIMESTAMP_KEYS:
            return "WEBSOCKET"
        return "UNKNOWN"
    if isinstance(value, int) and not isinstance(value, bool):
        return "EPOCH_SECONDS"
    if isinstance(value, str):
        return "ISO8601"
    return "UNKNOWN"


def to_timestamp_ns(value: Any, *, label: str) -> int:
    """UTC epoch nanoseconds from a documented-safe encoding.

    Accepted: REST ``{"s": s[, "ns": n]}`` and WebSocket
    ``{"seconds": s[, "nanoseconds": n]}`` (exact key sets, never mixed),
    integer epoch seconds, or an ISO-8601 string with an explicit offset.
    """
    if isinstance(value, dict):
        encoding = timestamp_encoding(value)
        if encoding == "REST":
            seconds, nanos = value.get("s"), value.get("ns", 0)
        elif encoding == "WEBSOCKET":
            seconds, nanos = value.get("seconds"), value.get("nanoseconds", 0)
        else:
            raise _mismatch(f"{label} has mixed or unknown timestamp keys {sorted(value)}")
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not isinstance(nanos, int) or isinstance(nanos, bool):
            raise _mismatch(f"{label} seconds/nanoseconds must be integers")
        if not 0 <= nanos < 1_000_000_000:
            raise _mismatch(f"{label} nanoseconds out of range")
        if not 0 <= seconds < _MAX_EPOCH_SECONDS:
            raise _mismatch(f"{label} seconds out of range")
        return seconds * 1_000_000_000 + nanos
    if isinstance(value, int) and not isinstance(value, bool):
        if not 0 <= value < _MAX_EPOCH_SECONDS:
            raise _mismatch(f"{label} integer is not epoch seconds (ambiguous unit)")
        return value * 1_000_000_000
    if isinstance(value, str):
        # Python keeps microseconds: ISO strings with finer digits are rejected
        # rather than silently truncated.
        if re.search(r"\.\d{7,}", value):
            raise _mismatch(f"{label} has sub-microsecond digits in ISO form")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise _mismatch(f"{label} has no timezone")
            parsed = parsed.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            raise _mismatch(f"{label} is not a valid ISO-8601 instant") from None
        if parsed.year < 1970:
            raise _mismatch(f"{label} is before the epoch")
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
    documented_envelope: bool = False
    series_ids: list[dict[str, str]] = field(default_factory=list)
    side_location: str | None = None
    timestamp_encodings: set[str] = field(default_factory=set)


SERIES_ID_FIELDS = ("type", "exchange", "rawSymbol", "normalizedSymbol", "category", "interval", "coin", "side")
EXPECTED_ID_FIELDS = ("type", "exchange", "rawSymbol", "interval")


def _is_point_list(node: Any) -> bool:
    return (
        isinstance(node, list)
        and bool(node)
        and all(isinstance(item, dict) for item in node)
        and any("timestamp" in item and "close" in item for item in node)
    )


def is_empty_result(payload: Any) -> bool:
    """True when the payload holds lists but none contains any point (empty window)."""
    def walk(node: Any, depth: int) -> tuple[bool, bool]:  # (has_list, has_point)
        if depth > _MAX_DEPTH:
            return False, False
        if isinstance(node, list):
            if any(isinstance(item, dict) and "timestamp" in item for item in node):
                return True, True
            results = [walk(item, depth + 1) for item in node]
            return True, any(point for _, point in results)
        if isinstance(node, dict):
            results = [walk(value, depth + 1) for value in node.values()]
            return any(has for has, _ in results), any(point for _, point in results)
        return False, False
    has_list, has_point = walk(payload, 0)
    return has_list and not has_point


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


def _build_point(item: dict, label: str, side: str | None, result: ParsedSeries, *, rest_only: bool) -> None:
    result.unexpected_fields.update(set(item) - CANDLE_FIELDS - ({"side"} if not rest_only else set()))
    missing = [name for name in CANDLE_REQUIRED if item.get(name) is None]
    if missing:
        result.rejected.append(f"{label}: missing {','.join(missing)}")
        return
    if not rest_only:
        own_side = item.get("side")
        if own_side is not None and own_side != side:
            result.rejected.append(f"{label}: point side {own_side!r} contradicts series side {side!r}")
            return
    stamps = {name: item[name] for name in ("timestamp", "firstTimestamp", "lastTimestamp") if item.get(name) is not None}
    encodings = {timestamp_encoding(value) for value in stamps.values()}
    if rest_only and encodings != {"REST"}:
        result.rejected.append(f"{label}: REST timestamp schema {{s[,ns]}} expected, got {sorted(encodings)}")
        return
    try:
        point = CandlePoint(
            side=side,
            timestamp_ns=to_timestamp_ns(item["timestamp"], label=f"{label}.timestamp"),
            open=to_decimal(item["open"], label=f"{label}.open"),
            high=to_decimal(item["high"], label=f"{label}.high"),
            low=to_decimal(item["low"], label=f"{label}.low"),
            close=to_decimal(item["close"], label=f"{label}.close"),
            volume=to_decimal(item["volume"], label=f"{label}.volume"),
            first_timestamp_ns=(
                to_timestamp_ns(stamps["firstTimestamp"], label=f"{label}.firstTimestamp") if "firstTimestamp" in stamps else None
            ),
            last_timestamp_ns=(
                to_timestamp_ns(stamps["lastTimestamp"], label=f"{label}.lastTimestamp") if "lastTimestamp" in stamps else None
            ),
        )
    except OpenMarketError as error:
        result.rejected.append(f"{label}: {error}")
        return
    if point.first_timestamp_ns is not None and point.last_timestamp_ns is not None and (
        point.first_timestamp_ns > point.last_timestamp_ns
    ):
        result.rejected.append(f"{label}: firstTimestamp after lastTimestamp")
        return
    if point.low > min(point.open, point.close) or point.high < max(point.open, point.close) or point.volume < 0:
        result.rejected.append(f"{label}: invalid OHLC/volume relationship")
        return
    result.timestamp_encodings.update(encodings)
    result.points.append(point)


def _parse_documented(series: Any, *, per_side: bool, expected: Mapping[str, str] | None) -> ParsedSeries:
    """The documented REST envelope; every structural deviation is a mismatch."""
    if not isinstance(series, list):
        raise _mismatch("series must be a list")
    result = ParsedSeries(documented_envelope=True, side_location="series[].id.side" if per_side else None)
    if not per_side and len(series) > 1:
        raise _mismatch("side-agnostic response contains more than one series (one instrument was requested)")
    seen_sides: set[str] = set()
    for index, item in enumerate(series):
        where = f"series[{index}]"
        if not isinstance(item, dict) or not isinstance(item.get("id"), dict) or not isinstance(item.get("points"), list):
            raise _mismatch(f"{where} must contain an id object and a points list")
        series_id = item["id"]
        for name in EXPECTED_ID_FIELDS:
            if expected is not None and series_id.get(name) != expected.get(name):
                raise _mismatch(f"{where}.id.{name} does not match the request")
        side = series_id.get("side")
        if per_side:
            if side not in SIDES:
                raise _mismatch(f"{where}.id.side missing or invalid (BUY|SELL expected)")
            if side in seen_sides:
                raise _mismatch(f"{where}.id.side duplicate {side} series")
            seen_sides.add(side)
        elif "side" in series_id:
            raise _mismatch(f"{where}.id.side present on a side-agnostic series")
        result.series_ids.append({name: series_id[name] for name in SERIES_ID_FIELDS if isinstance(series_id.get(name), str)})
        result.envelope_paths.append(f"$.{where}.points[*].Point")
        for point_index, wrapper in enumerate(item["points"]):
            label = f"{where}.points[{point_index}]"
            if not isinstance(wrapper, dict) or not isinstance(wrapper.get("Point"), dict):
                raise _mismatch(f"{label} must be a {{\"Point\": {{...}}}} wrapper")
            _build_point(wrapper["Point"], label, side if per_side else None, result, rest_only=True)
    return result


def parse_candles(payload: Any, *, per_side: bool, expected: Mapping[str, str] | None = None) -> ParsedSeries:
    """Documented envelope first (strict); structural fallback only for other shapes.

    ``expected`` (type, exchange, rawSymbol, interval) is checked against every
    ``series[].id`` on the documented path.
    """
    if isinstance(payload, dict) and "series" in payload:
        return _parse_documented(payload["series"], per_side=per_side, expected=expected)
    found: list[tuple[str, str | None, list]] = []
    _walk(payload, "$", None, 0, found)
    if not found:
        if is_empty_result(payload):
            return ParsedSeries()  # empty window: no points, nothing invented
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
            _build_point(item, f"{path}[{index}]", side if per_side else None, result, rest_only=False)
    return result
