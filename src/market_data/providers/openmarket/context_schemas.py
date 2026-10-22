"""Parsing of OpenMarket context types: open interest, funding, liquidations, volume profile.

Formats are taken from real responses captured on the target host on
2026-10-21 (``scripts/openmarket_capture_samples.py``, BINANCE_FUTURES BTCUSDT,
HOUR and FIFTEEN_MINUTES). They share the documented REST envelope
``{"series": [{"id": {...}, "points": [{"Point": {...}}]}]}`` and the REST
timestamp ``{"s"[, "ns"]}``:

=====================  ==========================================================  ======
type                   Point fields                                                series
=====================  ==========================================================  ======
OPEN_INTEREST_AGG      open, high, low, close, timestamp                           one
FUNDING_RATE_AGG       rateOpen, rateHigh, rateLow, rateClose, timestamp           one
LIQUIDATION_AGG        liquidations, timestamp                                     BUY and/or SELL in ``id.side``
VOLUME_PROFILE_AGG     profile (flat list ``[price, buy_vol, sell_vol, ...]``),    one
                       timestamp
=====================  ==========================================================  ======

Observed in the capture (not documented by OpenMarket):

- Units: OI and liquidations are reported in coin (values ~97k for BTC OI while
  BTC traded ~83k; not USD); kept ``as_reported_by_provider``.
- LIQUIDATION_AGG omits intervals without liquidations, and one series came
  back unsorted. Missing intervals are read as zero only *inside* a series that
  exists; points are always re-sorted.
- VOLUME_PROFILE_AGG points arrive newest first; the buy/sell columns of each
  closed hour summed exactly to TRADE_AGG BUY/SELL volume of that hour.
- The end of the window is inclusive (also for these types): the interval that
  starts at ``from+period`` is returned and is the running one.
- TPO_AGG answered HTTP 500 ``{"code":13,"message":"internal error"}`` for both
  windows; it is not parsed here.

Every structural deviation on the documented path is a ``SCHEMA_MISMATCH``;
invalid single points are rejected and reported, never repaired.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping

from .errors import OpenMarketError, OpenMarketErrorKind
from .schemas import SIDES, timestamp_encoding, to_decimal, to_timestamp_ns

OPEN_INTEREST = "OPEN_INTEREST_AGG"
FUNDING_RATE = "FUNDING_RATE_AGG"
LIQUIDATION = "LIQUIDATION_AGG"
VOLUME_PROFILE = "VOLUME_PROFILE_AGG"
TPO = "TPO_AGG"

_FIELDS = {
    OPEN_INTEREST: frozenset({"open", "high", "low", "close", "timestamp"}),
    FUNDING_RATE: frozenset({"rateOpen", "rateHigh", "rateLow", "rateClose", "timestamp"}),
    LIQUIDATION: frozenset({"liquidations", "timestamp"}),
    VOLUME_PROFILE: frozenset({"profile", "timestamp"}),
}
_PER_SIDE = frozenset({LIQUIDATION})
_EXPECTED_ID = ("type", "exchange", "rawSymbol", "interval")
_MAX_PROFILE_ROWS = 20_000


def _mismatch(message: str) -> OpenMarketError:
    return OpenMarketError(OpenMarketErrorKind.SCHEMA_MISMATCH, message)


@dataclass(frozen=True, slots=True)
class OhlcPoint:
    """OPEN_INTEREST_AGG (contracts/coin) or FUNDING_RATE_AGG (fraction per funding interval)."""

    timestamp_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class LiquidationPoint:
    side: str  # BUY | SELL as reported in series[].id.side
    timestamp_ns: int
    liquidations: Decimal


@dataclass(frozen=True, slots=True)
class ProfileRow:
    price: Decimal
    buy_volume: Decimal
    sell_volume: Decimal

    @property
    def total(self) -> Decimal:
        return self.buy_volume + self.sell_volume


@dataclass(frozen=True, slots=True)
class ProfilePoint:
    timestamp_ns: int
    rows: tuple[ProfileRow, ...]


@dataclass(slots=True)
class ParsedContextSeries:
    data_type: str
    points: list[Any] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    unexpected_fields: set[str] = field(default_factory=set)
    sides: list[str] = field(default_factory=list)
    reordered: bool = False


def _ohlc(item: Mapping[str, Any], label: str, names: tuple[str, str, str, str], *, non_negative: bool) -> OhlcPoint:
    o, h, l, c = (to_decimal(item[name], label=f"{label}.{name}") for name in names)
    if l > min(o, c) or h < max(o, c):
        raise _mismatch(f"{label}: invalid open/high/low/close relationship")
    if non_negative and l < 0:
        raise _mismatch(f"{label}: negative open interest")
    return OhlcPoint(to_timestamp_ns(item["timestamp"], label=f"{label}.timestamp"), o, h, l, c)


def _profile(item: Mapping[str, Any], label: str) -> ProfilePoint:
    raw = item["profile"]
    if not isinstance(raw, list) or len(raw) % 3:
        raise _mismatch(f"{label}.profile must be a flat list of [price, buy, sell] triples")
    if len(raw) // 3 > _MAX_PROFILE_ROWS:
        raise _mismatch(f"{label}.profile has too many rows")
    rows: list[ProfileRow] = []
    seen: set[Decimal] = set()
    for index in range(0, len(raw), 3):
        price = to_decimal(raw[index], label=f"{label}.profile[{index}]")
        buy = to_decimal(raw[index + 1], label=f"{label}.profile[{index + 1}]")
        sell = to_decimal(raw[index + 2], label=f"{label}.profile[{index + 2}]")
        if price <= 0 or buy < 0 or sell < 0:
            raise _mismatch(f"{label}.profile row {index // 3}: price must be > 0, volumes >= 0")
        if price in seen:
            raise _mismatch(f"{label}.profile row {index // 3}: duplicate price level")
        seen.add(price)
        rows.append(ProfileRow(price, buy, sell))
    rows.sort(key=lambda row: row.price)
    return ProfilePoint(to_timestamp_ns(item["timestamp"], label=f"{label}.timestamp"), tuple(rows))


def _build(data_type: str, item: Mapping[str, Any], label: str, side: str | None) -> Any:
    if data_type == OPEN_INTEREST:
        return _ohlc(item, label, ("open", "high", "low", "close"), non_negative=True)
    if data_type == FUNDING_RATE:
        return _ohlc(item, label, ("rateOpen", "rateHigh", "rateLow", "rateClose"), non_negative=False)
    if data_type == LIQUIDATION:
        value = to_decimal(item["liquidations"], label=f"{label}.liquidations")
        if value < 0:
            raise _mismatch(f"{label}: negative liquidations")
        return LiquidationPoint(side or "", to_timestamp_ns(item["timestamp"], label=f"{label}.timestamp"), value)
    return _profile(item, label)


def parse_context_series(payload: Any, *, data_type: str, expected: Mapping[str, str] | None = None) -> ParsedContextSeries:
    """Strict documented-envelope parsing for one context type."""
    if data_type not in _FIELDS:
        raise ValueError(f"unsupported context type {data_type}")
    if not isinstance(payload, dict) or "series" not in payload:
        raise _mismatch("documented series envelope expected")
    series = payload["series"]
    if not isinstance(series, list):
        raise _mismatch("series must be a list")
    per_side = data_type in _PER_SIDE
    if not per_side and len(series) > 1:
        raise _mismatch(f"{data_type} response contains more than one series (one instrument was requested)")
    result = ParsedContextSeries(data_type=data_type)
    required = _FIELDS[data_type]
    for index, entry in enumerate(series):
        where = f"series[{index}]"
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), dict) or not isinstance(entry.get("points"), list):
            raise _mismatch(f"{where} must contain an id object and a points list")
        series_id = entry["id"]
        for name in _EXPECTED_ID:
            if expected is not None and series_id.get(name) != expected.get(name):
                raise _mismatch(f"{where}.id.{name} does not match the request")
        side = series_id.get("side")
        if per_side:
            if not isinstance(side, str) or side not in SIDES:
                raise _mismatch(f"{where}.id.side missing or invalid (BUY|SELL expected)")
            if side in result.sides:
                raise _mismatch(f"{where}.id.side duplicate {side} series")
            result.sides.append(side)
        elif "side" in series_id:
            raise _mismatch(f"{where}.id.side present on a single-series type")
        previous: int | None = None
        for point_index, wrapper in enumerate(entry["points"]):
            label = f"{where}.points[{point_index}]"
            if not isinstance(wrapper, dict) or not isinstance(wrapper.get("Point"), dict):
                raise _mismatch(f"{label} must be a {{\"Point\": {{...}}}} wrapper")
            item = wrapper["Point"]
            result.unexpected_fields.update(set(item) - required)
            missing = sorted(name for name in required if item.get(name) is None)
            if missing:
                result.rejected.append(f"{label}: missing {','.join(missing)}")
                continue
            if timestamp_encoding(item["timestamp"]) != "REST":
                result.rejected.append(f"{label}: REST timestamp schema {{s[,ns]}} expected")
                continue
            try:
                point = _build(data_type, item, label, side if per_side else None)
            except OpenMarketError as error:
                result.rejected.append(f"{label}: {error}")
                continue
            if previous is not None and point.timestamp_ns < previous:
                result.reordered = True
            previous = point.timestamp_ns
            result.points.append(point)
    _dedupe(result)
    return result


def _dedupe(result: ParsedContextSeries) -> None:
    """Identical duplicates collapse; contradicting ones are dropped and reported."""
    def key(point: Any) -> tuple:
        return (getattr(point, "side", ""), point.timestamp_ns)

    kept: dict[tuple, Any] = {}
    conflicted: set[tuple] = set()
    for point in result.points:
        k = key(point)
        if k in conflicted:
            continue
        if k not in kept:
            kept[k] = point
        elif kept[k] != point:
            conflicted.add(k)
            del kept[k]
            result.rejected.append(f"conflicting duplicate {k[0] or 'ALL'}@{k[1]}")
    result.points = sorted(kept.values(), key=key)


def closed_points(points: list[Any], *, from_seconds: int, period_seconds: int, interval_seconds: int, now_seconds: int) -> tuple[list[Any], list[str], int]:
    """Points of closed intervals inside ``[from, from+period)``.

    The interval starting exactly at ``from+period`` (inclusive window end on
    OpenMarket's side) and the running interval are excluded and counted; any
    other point outside the window is rejected.
    """
    start_ns, end_ns = from_seconds * 1_000_000_000, (from_seconds + period_seconds) * 1_000_000_000
    length_ns, now_ns = interval_seconds * 1_000_000_000, now_seconds * 1_000_000_000
    kept, rejected, excluded = [], [], 0
    for point in points:
        label = f"{getattr(point, 'side', '') or 'ALL'}@{point.timestamp_ns}"
        if point.timestamp_ns == end_ns:
            excluded += 1  # documented inclusive window end
            continue
        if not start_ns <= point.timestamp_ns < end_ns:
            rejected.append(f"{label}: outside requested window")
            continue
        if (point.timestamp_ns - start_ns) % length_ns:
            rejected.append(f"{label}: not on the interval grid")
            continue
        if point.timestamp_ns + length_ns > now_ns:
            excluded += 1  # running interval
            continue
        kept.append(point)
    return kept, rejected, excluded


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    point_of_control: Decimal
    value_area_high: Decimal
    value_area_low: Decimal
    total_volume: Decimal
    buy_volume: Decimal
    sell_volume: Decimal
    rows: int
    intervals: int
    value_area_fraction: Decimal


def summarize_profile(points: list[ProfilePoint], *, value_area_fraction: Decimal = Decimal("0.70")) -> ProfileSummary | None:
    """Aggregate per-interval profiles into POC and value area.

    POC: price level with the largest buy+sell volume (ties: lower price).
    Value area: grows from the POC, each step adding the neighbouring level with
    more volume (ties: the higher level), until ``value_area_fraction`` of the
    total is covered. VAH/VAL are price levels as reported (bucket prices).
    """
    totals: dict[Decimal, list[Decimal]] = {}
    for point in points:
        for row in point.rows:
            bucket = totals.setdefault(row.price, [Decimal(0), Decimal(0)])
            bucket[0] += row.buy_volume
            bucket[1] += row.sell_volume
    if not totals:
        return None
    prices = sorted(totals)
    volume = [totals[price][0] + totals[price][1] for price in prices]
    total = sum(volume, Decimal(0))
    if total <= 0:
        return None
    poc_index = min(range(len(prices)), key=lambda i: (-volume[i], prices[i]))
    low = high = poc_index
    covered = volume[poc_index]
    target = total * value_area_fraction
    while covered < target and (low > 0 or high < len(prices) - 1):
        below = volume[low - 1] if low > 0 else None
        above = volume[high + 1] if high < len(prices) - 1 else None
        if above is not None and (below is None or above >= below):
            high += 1
            covered += above
        else:
            low -= 1
            covered += below
    return ProfileSummary(
        point_of_control=prices[poc_index],
        value_area_high=prices[high],
        value_area_low=prices[low],
        total_volume=total,
        buy_volume=sum((totals[p][0] for p in prices), Decimal(0)),
        sell_volume=sum((totals[p][1] for p in prices), Decimal(0)),
        rows=len(prices),
        intervals=len(points),
        value_area_fraction=value_area_fraction,
    )


def liquidation_totals(points: list[LiquidationPoint], sides: list[str]) -> dict[str, Decimal | None]:
    """Sum per reported side. A side without a series is None (unknown), not zero."""
    totals: dict[str, Decimal | None] = {"BUY": None, "SELL": None}
    for side in sides:
        totals[side] = sum((p.liquidations for p in points if p.side == side), Decimal(0))
    return totals

