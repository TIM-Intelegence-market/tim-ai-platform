"""Positioning and market-profile context: funding, liquidations, open interest,
orderbook depth, volume profile and TPO.

Two parts:

1. Parsing (``parse_context``): turns the optional JSON fields of an adapter
   input into validated, typed values. Nothing is guessed; a malformed field is
   dropped and reported, never repaired.
2. Interpretation (``interpret_positioning``, ``interpret_profile``):
   deterministic, typed statements (OBSERVATION / INTERPRETATION / HYPOTHESIS)
   plus a machine-readable summary. Thresholds are heuristics, not calibrated
   statistics; no statement here is ever a CONFIRMATION. Orderbook depth only
   produces observations because resting liquidity can be pulled at any time.

JSON input (all fields optional; same keys for every adapter)::

    "funding_rate": 0.0001,              # fraction per funding interval (0.0001 = 0.01 %)
    "funding_interval_hours": 8,
    "liquidations": {"long_volume": 120.5, "short_volume": 30.2},
    "open_interest": [{"time": "...Z", "value": 102340}, ...],
    "orderbook_depth": [{"depth_pct": 2.5, "imbalance": -0.203},
                        {"depth_pct": 5, "bid_volume": 900, "ask_volume": 1100}],
    "volume_profile": {"poc": 83200, "vah": 83600, "val": 82900},
    "tpo": {"poc": 83250, "vah": 83550, "val": 82950, "ib_high": 83400,
            "ib_low": 83000, "poor_high": 83600, "poor_low": null,
            "naked_pocs": [82500, 84100]}
    "gamma": {"as_of": "...Z", "gamma_flip": 79410, "call_wall": 82000, "put_wall": 75000,
              "net_gex": 48600000, "max_pain": 78000, "expected_move_low": 77385,
              "expected_move_high": 82360, "source": "DERIBIT_PUBLIC_OPTIONS_BOOK_SUMMARY"}

``gamma`` is the ``analysis_input`` block of the Control Center's ``/api/gamma`` (or
``/api/prep`` -> ``gamma``): options levels estimated under the convention that
dealers are long calls and short puts. It only adds statements, never a score hint.

Orderbook ``imbalance`` is ``(bid - ask) / (bid + ask)`` within ``depth_pct``
percent of the mid price: negative means more resting asks than bids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence

from .domain import OrderflowStatement, OrderflowStatementKind

ZERO = Decimal("0")
ONE = Decimal("1")

# Heuristic thresholds (documented, uncalibrated).
FUNDING_ELEVATED_8H = Decimal("0.0002")  # 0.02 % per 8 h (twice the usual 0.01 % baseline)
FUNDING_EXTREME_8H = Decimal("0.0005")  # 0.05 % per 8 h
LIQUIDATION_DOMINANCE = Decimal("0.65")  # share of one side in total liquidations
OPEN_INTEREST_FLAT = Decimal("0.005")  # |change| below 0.5 % over the window is FLAT
ORDERBOOK_IMBALANCE_NOTABLE = Decimal("0.15")
MAX_FUNDING_ABS = Decimal("0.05")  # 5 % per interval is not a plausible funding value


def _dec(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{label} is not numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{label} is not numeric") from None
    if not result.is_finite():
        raise ValueError(f"{label} is not finite")
    return result


def _price(value: Any, label: str) -> Decimal | None:
    if value is None:
        return None
    result = _dec(value, label)
    if result <= ZERO:
        raise ValueError(f"{label} must be positive")
    return result


def _time(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if text[-1:] in ("Z", "z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            raise ValueError(f"{label} is not ISO-8601") from None
    else:
        raise ValueError(f"{label} is not ISO-8601")
    if parsed.tzinfo is None:
        raise ValueError(f"{label} has no timezone")
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class OrderbookDepth:
    depth_pct: Decimal
    imbalance: Decimal  # (bid - ask) / (bid + ask), within [-1, 1]

    def __post_init__(self) -> None:
        if self.depth_pct <= ZERO or self.depth_pct > Decimal("100"):
            raise ValueError("depth_pct must be within (0, 100]")
        if not (-ONE <= self.imbalance <= ONE):
            raise ValueError("imbalance must be within [-1, 1]")


@dataclass(frozen=True, slots=True)
class PositioningInputs:
    funding_rate: Decimal | None = None
    funding_interval_hours: int = 8
    long_liquidation_volume: Decimal | None = None
    short_liquidation_volume: Decimal | None = None
    open_interest: tuple[tuple[datetime, Decimal], ...] = ()
    orderbook_depth: tuple[OrderbookDepth, ...] = ()

    def __post_init__(self) -> None:
        if not 1 <= self.funding_interval_hours <= 24:
            raise ValueError("funding_interval_hours must be within [1, 24]")
        if self.funding_rate is not None and abs(self.funding_rate) > MAX_FUNDING_ABS:
            raise ValueError("funding_rate is a fraction per interval (0.0001 = 0.01 %); value is implausible")
        for label, value in (("long_liquidation_volume", self.long_liquidation_volume), ("short_liquidation_volume", self.short_liquidation_volume)):
            if value is not None and value < ZERO:
                raise ValueError(f"{label} cannot be negative")
        times = [stamp for stamp, _ in self.open_interest]
        if times != sorted(times) or len(set(times)) != len(times):
            raise ValueError("open_interest must be strictly ordered by time")
        if any(value < ZERO for _, value in self.open_interest):
            raise ValueError("open_interest cannot be negative")

    @property
    def funding_rate_8h(self) -> Decimal | None:
        if self.funding_rate is None:
            return None
        return self.funding_rate * Decimal(8) / Decimal(self.funding_interval_hours)

    def is_empty(self) -> bool:
        return (
            self.funding_rate is None
            and self.long_liquidation_volume is None
            and self.short_liquidation_volume is None
            and not self.open_interest
            and not self.orderbook_depth
        )


@dataclass(frozen=True, slots=True)
class ProfileLevels:
    """Volume-profile and TPO reference levels. ``source`` names where each came from."""

    point_of_control: Decimal | None = None
    value_area_high: Decimal | None = None
    value_area_low: Decimal | None = None
    initial_balance_high: Decimal | None = None
    initial_balance_low: Decimal | None = None
    poor_high: Decimal | None = None
    poor_low: Decimal | None = None
    naked_pocs: tuple[Decimal, ...] = ()
    source: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.value_area_high is not None and self.value_area_low is not None and self.value_area_high < self.value_area_low:
            raise ValueError("value_area_high must be >= value_area_low")
        if (
            self.initial_balance_high is not None
            and self.initial_balance_low is not None
            and self.initial_balance_high < self.initial_balance_low
        ):
            raise ValueError("initial_balance_high must be >= initial_balance_low")
        if self.point_of_control is not None and self.value_area_high is not None and self.value_area_low is not None:
            if not self.value_area_low <= self.point_of_control <= self.value_area_high:
                raise ValueError("point_of_control must lie inside the value area")

    def is_empty(self) -> bool:
        return all(
            getattr(self, name) is None
            for name in ("point_of_control", "value_area_high", "value_area_low", "initial_balance_high", "initial_balance_low", "poor_high", "poor_low")
        ) and not self.naked_pocs


@dataclass(frozen=True, slots=True)
class GammaContext:
    """Options gamma levels (estimates; see the module docstring)."""

    gamma_flip: Decimal | None = None
    call_wall: Decimal | None = None
    put_wall: Decimal | None = None
    max_pain: Decimal | None = None
    net_gex: Decimal | None = None
    expected_move_low: Decimal | None = None
    expected_move_high: Decimal | None = None
    as_of: datetime | None = None
    source: str | None = None

    def __post_init__(self) -> None:
        if self.call_wall is not None and self.put_wall is not None and self.call_wall < self.put_wall:
            raise ValueError("call_wall must be >= put_wall")
        if self.expected_move_low is not None and self.expected_move_high is not None and self.expected_move_low > self.expected_move_high:
            raise ValueError("expected_move_low must be <= expected_move_high")

    def is_empty(self) -> bool:
        return all(getattr(self, name) is None for name in ("gamma_flip", "call_wall", "put_wall", "max_pain", "net_gex", "expected_move_low", "expected_move_high"))


@dataclass(slots=True)
class ParsedContext:
    positioning: PositioningInputs | None = None
    profile: ProfileLevels | None = None
    gamma: GammaContext | None = None
    rejected: list[str] = field(default_factory=list)


def _parse_gamma(raw: Any, rejected: list[str]) -> GammaContext | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        rejected.append("gamma:not_an_object")
        return None
    values: dict[str, Any] = {}
    for key in ("gamma_flip", "call_wall", "put_wall", "max_pain", "expected_move_low", "expected_move_high"):
        try:
            values[key] = _price(raw.get(key), f"gamma.{key}")
        except ValueError as exc:
            rejected.append(f"gamma.{key}:{exc}")
    if raw.get("net_gex") is not None:
        try:
            values["net_gex"] = _dec(raw["net_gex"], "gamma.net_gex")
        except ValueError as exc:
            rejected.append(f"gamma.net_gex:{exc}")
    if raw.get("as_of") is not None:
        try:
            values["as_of"] = _time(raw["as_of"], "gamma.as_of")
        except ValueError as exc:
            rejected.append(f"gamma.as_of:{exc}")
    if isinstance(raw.get("source"), str):
        values["source"] = raw["source"][:80]
    try:
        gamma = GammaContext(**values)
    except ValueError as exc:
        rejected.append(f"gamma:{exc}")
        return None
    return None if gamma.is_empty() else gamma


def _parse_orderbook(raw: Any, rejected: list[str]) -> tuple[OrderbookDepth, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        rejected.append("orderbook_depth:not_a_list")
        return ()
    result: list[OrderbookDepth] = []
    seen: set[Decimal] = set()
    for index, item in enumerate(raw):
        label = f"orderbook_depth[{index}]"
        try:
            if not isinstance(item, Mapping):
                raise ValueError("not an object")
            depth = _dec(item.get("depth_pct"), "depth_pct")
            imbalance = _dec(item["imbalance"], "imbalance") if item.get("imbalance") is not None else None
            if item.get("bid_volume") is not None or item.get("ask_volume") is not None:
                bid = _dec(item.get("bid_volume"), "bid_volume")
                ask = _dec(item.get("ask_volume"), "ask_volume")
                if bid < ZERO or ask < ZERO or bid + ask == ZERO:
                    raise ValueError("bid_volume/ask_volume must be >= 0 and not both zero")
                computed = (bid - ask) / (bid + ask)
                if imbalance is not None and abs(imbalance - computed) > Decimal("0.001"):
                    raise ValueError("imbalance contradicts bid_volume/ask_volume")
                imbalance = computed if imbalance is None else imbalance
            if imbalance is None:
                raise ValueError("imbalance or bid_volume/ask_volume required")
            if depth in seen:
                raise ValueError("duplicate depth_pct")
            seen.add(depth)
            result.append(OrderbookDepth(depth_pct=depth, imbalance=imbalance))
        except ValueError as exc:
            rejected.append(f"{label}:{exc}")
    return tuple(sorted(result, key=lambda item: item.depth_pct))


def _parse_open_interest(raw: Any, rejected: list[str]) -> tuple[tuple[datetime, Decimal], ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        rejected.append("open_interest:not_a_list")
        return ()
    points: dict[datetime, Decimal] = {}
    conflicts: set[datetime] = set()
    for index, item in enumerate(raw):
        try:
            if not isinstance(item, Mapping):
                raise ValueError("not an object")
            stamp = _time(item.get("time"), "time")
            value = _dec(item.get("value"), "value")
            if value < ZERO:
                raise ValueError("value cannot be negative")
        except ValueError as exc:
            rejected.append(f"open_interest[{index}]:{exc}")
            continue
        if stamp in points and points[stamp] != value:
            conflicts.add(stamp)
        points.setdefault(stamp, value)
    for stamp in conflicts:  # contradicting values: neither is kept
        points.pop(stamp, None)
        rejected.append(f"open_interest:conflicting_values_at={stamp.isoformat()}")
    return tuple(sorted(points.items()))


def _parse_profile(data: Mapping[str, Any], rejected: list[str]) -> ProfileLevels | None:
    volume = data.get("volume_profile")
    tpo = data.get("tpo")
    values: dict[str, Any] = {}
    sources: list[str] = []
    naked: list[Decimal] = []

    def take(section: Any, name: str, keys: Sequence[tuple[str, str]]) -> None:
        if section is None:
            return
        if not isinstance(section, Mapping):
            rejected.append(f"{name}:not_an_object")
            return
        used = False
        for key, target in keys:
            if section.get(key) is None or values.get(target) is not None:
                continue
            try:
                values[target] = _price(section[key], f"{name}.{key}")
                used = True
            except ValueError as exc:
                rejected.append(f"{name}.{key}:{exc}")
        if used:
            sources.append(name)

    # POC and value area come from one source only (volume profile first, else TPO): never a
    # value area mixed from two methods. TPO always adds IB, poor highs/lows and naked POCs.
    core = (("poc", "point_of_control"), ("vah", "value_area_high"), ("val", "value_area_low"))
    extras = (("ib_high", "initial_balance_high"), ("ib_low", "initial_balance_low"), ("poor_high", "poor_high"), ("poor_low", "poor_low"))
    take(volume, "volume_profile", core)
    core_from_volume = any(values.get(target) is not None for _, target in core)
    if core_from_volume and isinstance(tpo, Mapping) and any(tpo.get(key) is not None for key, _ in core):
        rejected.append("tpo:poc_value_area_ignored_volume_profile_used")
    take(tpo, "tpo", extras if core_from_volume else core + extras)
    if isinstance(tpo, Mapping) and tpo.get("naked_pocs") is not None:
        raw = tpo["naked_pocs"]
        if isinstance(raw, list):
            for index, item in enumerate(raw):
                try:
                    price = _price(item, f"tpo.naked_pocs[{index}]")
                    if price is not None:
                        naked.append(price)
                except ValueError as exc:
                    rejected.append(f"tpo.naked_pocs[{index}]:{exc}")
            if naked and "tpo" not in sources:
                sources.append("tpo")
        else:
            rejected.append("tpo.naked_pocs:not_a_list")
    if not values and not naked:
        return None
    try:
        return ProfileLevels(**values, naked_pocs=tuple(sorted(set(naked))), source=tuple(sources))
    except ValueError as exc:
        rejected.append(f"profile:{exc}")
        return None


def parse_context(data: Mapping[str, Any]) -> ParsedContext:
    """Validated positioning and profile values from an adapter payload."""
    result = ParsedContext()
    rejected = result.rejected
    funding = None
    interval = 8
    interval_ok = True
    raw_interval = data.get("funding_interval_hours")
    if raw_interval is not None:
        if isinstance(raw_interval, int) and not isinstance(raw_interval, bool) and 1 <= raw_interval <= 24:
            interval = raw_interval
        else:
            interval_ok = False
            rejected.append("funding_interval_hours:integer_1_to_24_expected")
    if data.get("funding_rate") is not None:
        try:
            funding = _dec(data["funding_rate"], "funding_rate")
            if abs(funding) > MAX_FUNDING_ABS:
                raise ValueError("implausible: a fraction per interval is expected (0.0001 = 0.01 %)")
            if not interval_ok:
                raise ValueError("dropped because funding_interval_hours is invalid")
        except ValueError as exc:
            rejected.append(f"funding_rate:{exc}")
            funding = None
    long_liq = short_liq = None
    liquidations = data.get("liquidations")
    if liquidations is not None:
        if isinstance(liquidations, Mapping):
            for key in ("long_volume", "short_volume"):
                if liquidations.get(key) is None:
                    continue
                try:
                    value = _dec(liquidations[key], f"liquidations.{key}")
                    if value < ZERO:
                        raise ValueError(f"liquidations.{key} cannot be negative")
                except ValueError as exc:
                    rejected.append(f"liquidations.{key}:{exc}")
                    continue
                if key == "long_volume":
                    long_liq = value
                else:
                    short_liq = value
        else:
            rejected.append("liquidations:not_an_object")
    open_interest = _parse_open_interest(data.get("open_interest"), rejected)
    orderbook = _parse_orderbook(data.get("orderbook_depth"), rejected)
    try:
        positioning = PositioningInputs(
            funding_rate=funding,
            funding_interval_hours=interval,
            long_liquidation_volume=long_liq,
            short_liquidation_volume=short_liq,
            open_interest=open_interest,
            orderbook_depth=orderbook,
        )
    except ValueError as exc:
        rejected.append(f"positioning:{exc}")
        positioning = None
    result.positioning = None if positioning is None or positioning.is_empty() else positioning
    result.profile = _parse_profile(data, rejected)
    result.gamma = _parse_gamma(data.get("gamma"), rejected)
    return result


# --- Interpretation ---------------------------------------------------------------------------


def _statement(kind: OrderflowStatementKind, text: str, refs: tuple[str, ...], weight: str = "1") -> OrderflowStatement:
    return OrderflowStatement(kind=kind, text=text, evidence_refs=refs, weight=Decimal(weight))


def open_interest_trend(series: Sequence[tuple[datetime, Decimal]]) -> tuple[str | None, Decimal | None]:
    """RISING / FALLING / FLAT and the relative change from first to last point."""
    if len(series) < 2 or series[0][1] == ZERO:
        return None, None
    change = (series[-1][1] - series[0][1]) / series[0][1]
    if abs(change) < OPEN_INTEREST_FLAT:
        return "FLAT", change
    return ("RISING" if change > ZERO else "FALLING"), change


@dataclass(frozen=True, slots=True)
class PositioningResult:
    statements: tuple[OrderflowStatement, ...]
    summary: dict[str, Any]
    missing: tuple[str, ...]
    open_interest_trend: str | None = None
    open_interest_with_price: str | None = None


PRICE_FLAT = Decimal("0.001")


def _response(start: Decimal, end: Decimal) -> str:
    if start <= ZERO:
        return "UNKNOWN"
    move = (end - start) / start
    return "FLAT" if abs(move) < PRICE_FLAT else "UP" if move > ZERO else "DOWN"


def window_price_response(candles: Sequence[Any]) -> str:
    """First open to last close over all candles: the window funding/liquidations/OI describe."""
    if not candles:
        return "UNKNOWN"
    return _response(Decimal(str(candles[0].open)), Decimal(str(candles[-1].close)))


def open_interest_price_response(candles: Sequence[Any], series: Sequence[tuple[datetime, Decimal]]) -> str:
    """Price move over exactly the OI span: last close at or before the first and the last OI time.

    ``OUTSIDE_WINDOW`` when the OI series does not overlap the candles, ``UNKNOWN``
    when the price at the start of the span cannot be read from the candles.
    """
    if len(series) < 2 or not candles:
        return "UNKNOWN"
    first_time, last_time = series[0][0], series[-1][0]
    if last_time < candles[0].open_time or first_time > candles[-1].close_time:
        return "OUTSIDE_WINDOW"

    def price_at(moment: datetime) -> Decimal | None:
        closed = [c for c in candles if c.close_time <= moment]
        if closed:
            return Decimal(str(closed[-1].close))
        if candles[0].open_time == moment:
            return Decimal(str(candles[0].open))
        return None

    start, end = price_at(first_time), price_at(last_time)
    if start is None or end is None:
        return "UNKNOWN"
    return _response(start, end)


def interpret_positioning(
    positioning: PositioningInputs | None,
    price_response: str,
    open_interest_price: str | None = None,
) -> PositioningResult:
    """Deterministic reading of funding, liquidations, OI and orderbook depth.

    ``price_response`` is the price move over the whole data window (see
    ``window_price_response``); ``open_interest_price`` the move over the OI
    span (``open_interest_price_response``), defaulting to ``price_response``.
    Funding and liquidations carry no timestamps of their own: they are read as
    describing the supplied window.
    """
    statements: list[OrderflowStatement] = []
    missing: list[str] = []
    summary: dict[str, Any] = {}
    p = positioning or PositioningInputs()
    oi_price = price_response if open_interest_price is None else open_interest_price
    if oi_price == "OUTSIDE_WINDOW":
        missing.append("open_interest_series:outside_candle_window")
        p = PositioningInputs(
            funding_rate=p.funding_rate, funding_interval_hours=p.funding_interval_hours,
            long_liquidation_volume=p.long_liquidation_volume, short_liquidation_volume=p.short_liquidation_volume,
            orderbook_depth=p.orderbook_depth,
        )
        oi_price = "UNKNOWN"
    obs, interp, hyp = OrderflowStatementKind.OBSERVATION, OrderflowStatementKind.INTERPRETATION, OrderflowStatementKind.HYPOTHESIS

    # Funding.
    funding_state = None
    rate_8h = p.funding_rate_8h
    if rate_8h is None:
        missing.append("funding_rate")
    else:
        size = abs(rate_8h)
        level = "EXTREME" if size >= FUNDING_EXTREME_8H else "ELEVATED" if size >= FUNDING_ELEVATED_8H else "NEUTRAL"
        sign = "POSITIVE" if rate_8h > ZERO else "NEGATIVE" if rate_8h < ZERO else "ZERO"
        funding_state = f"{level}_{sign}" if level != "NEUTRAL" else "NEUTRAL"
        summary["funding"] = {"rate": str(p.funding_rate), "interval_hours": p.funding_interval_hours, "rate_8h": str(rate_8h), "state": funding_state}
        statements.append(_statement(obs, f"funding_rate_8h={rate_8h} state={funding_state}", ("funding_rate",)))
        if level != "NEUTRAL":
            crowd = "longs" if rate_8h > ZERO else "shorts"
            statements.append(_statement(interp, f"funding_{level.lower()}_{sign.lower()}_{crowd}_pay_to_hold", ("funding_rate",), "0.5" if level == "ELEVATED" else "0.6"))
            if level == "EXTREME":
                statements.append(_statement(hyp, f"{crowd}_crowded_squeeze_risk_{'down' if crowd == 'longs' else 'up'}", ("funding_rate",), "0.4"))

    # Liquidations.
    liq_state = None
    long_liq, short_liq = p.long_liquidation_volume, p.short_liquidation_volume
    if long_liq is None and short_liq is None:
        missing.append("liquidations")
    elif long_liq is None or short_liq is None:
        missing.append("liquidations:one_side_missing")
        summary["liquidations"] = {"long_volume": None if long_liq is None else str(long_liq), "short_volume": None if short_liq is None else str(short_liq), "state": "PARTIAL"}
    else:
        total = long_liq + short_liq
        if total == ZERO:
            liq_state = "NONE"
        else:
            long_share = long_liq / total
            liq_state = "LONGS_DOMINANT" if long_share >= LIQUIDATION_DOMINANCE else "SHORTS_DOMINANT" if (ONE - long_share) >= LIQUIDATION_DOMINANCE else "BALANCED"
        summary["liquidations"] = {"long_volume": str(long_liq), "short_volume": str(short_liq), "state": liq_state}
        statements.append(_statement(obs, f"liquidations long={long_liq} short={short_liq} state={liq_state}", ("liquidations",)))
        if liq_state == "LONGS_DOMINANT" and price_response == "DOWN":
            statements.append(_statement(interp, "long_liquidations_drive_price_down", ("liquidations", "candles"), "0.6"))
            statements.append(_statement(hyp, "long_flush_may_exhaust_selling", ("liquidations",), "0.4"))
        elif liq_state == "SHORTS_DOMINANT" and price_response == "UP":
            statements.append(_statement(interp, "short_liquidations_drive_price_up", ("liquidations", "candles"), "0.6"))
            statements.append(_statement(hyp, "short_squeeze_may_exhaust_buying", ("liquidations",), "0.4"))

    # Open interest series.
    trend, change = open_interest_trend(p.open_interest)
    with_price = None
    if trend is None:
        if not p.open_interest:
            missing.append("open_interest_series")
        elif len(p.open_interest) < 2:
            missing.append("open_interest_series:too_short")
        else:
            missing.append("open_interest_series:zero_base")
    else:
        if trend != "FLAT" and oi_price in {"UP", "DOWN"}:
            with_price = f"{trend}_WITH_PRICE_{oi_price}"
        elif oi_price == "UNKNOWN":
            missing.append("open_interest_series:price_over_span_unknown")
        summary["open_interest"] = {
            "points": len(p.open_interest), "first": str(p.open_interest[0][1]), "last": str(p.open_interest[-1][1]),
            "change_fraction": str(change.quantize(Decimal("0.0001"))), "trend": trend, "with_price": with_price,
        }
        statements.append(_statement(obs, f"open_interest_change={change.quantize(Decimal('0.0001'))} trend={trend}", ("open_interest",)))

    # Combination: new positions against the crowd's funding are fuel for a squeeze.
    if trend == "RISING" and funding_state in {"EXTREME_POSITIVE", "ELEVATED_POSITIVE"} and oi_price == "UP":
        statements.append(_statement(hyp, "crowded_longs_add_downside_liquidity", ("open_interest", "funding_rate"), "0.5"))
    elif trend == "RISING" and funding_state in {"EXTREME_NEGATIVE", "ELEVATED_NEGATIVE"} and oi_price == "DOWN":
        statements.append(_statement(hyp, "crowded_shorts_add_upside_liquidity", ("open_interest", "funding_rate"), "0.5"))
    if trend == "FALLING" and liq_state == "LONGS_DOMINANT":
        statements.append(_statement(interp, "open_interest_drop_matches_long_liquidations", ("open_interest", "liquidations"), "0.6"))
    elif trend == "FALLING" and liq_state == "SHORTS_DOMINANT":
        statements.append(_statement(interp, "open_interest_drop_matches_short_liquidations", ("open_interest", "liquidations"), "0.6"))

    # Orderbook depth: observation only (resting orders can be pulled).
    if not p.orderbook_depth:
        missing.append("orderbook_depth")
    else:
        depth_summary = []
        for item in p.orderbook_depth:
            side = "BID_HEAVY" if item.imbalance >= ORDERBOOK_IMBALANCE_NOTABLE else "ASK_HEAVY" if item.imbalance <= -ORDERBOOK_IMBALANCE_NOTABLE else "BALANCED"
            depth_summary.append({"depth_pct": str(item.depth_pct), "imbalance": str(item.imbalance), "state": side})
            statements.append(_statement(obs, f"orderbook_depth_{item.depth_pct}pct imbalance={item.imbalance} state={side}", ("orderbook_depth",)))
        summary["orderbook_depth"] = depth_summary
        summary["orderbook_note"] = "resting_liquidity_can_be_pulled_observation_only"

    summary["bias_hints"] = _bias_hints(funding_state, liq_state, trend, price_response)
    return PositioningResult(
        statements=tuple(statements),
        summary=summary,
        missing=tuple(missing),
        open_interest_trend=trend,
        open_interest_with_price=with_price,
    )


def _bias_hints(funding_state: str | None, liq_state: str | None, trend: str | None, price_response: str) -> list[str]:
    """Small, named score hints used by the probability engine (never a confirmation)."""
    hints: list[str] = []
    if funding_state == "EXTREME_POSITIVE":
        hints.append("against_long:crowded_funding")
    elif funding_state == "EXTREME_NEGATIVE":
        hints.append("against_short:crowded_funding")
    # Liquidations give no score hint: a flush can continue the move or exhaust it.
    return hints


def interpret_profile(profile: ProfileLevels | None, last_price: Decimal | None) -> tuple[tuple[OrderflowStatement, ...], dict[str, Any], tuple[str, ...]]:
    """Where price trades relative to value, IB and unfinished auctions."""
    if profile is None:
        return (), {}, ("volume_profile_or_tpo",)
    statements: list[OrderflowStatement] = []
    summary: dict[str, Any] = {"source": list(profile.source)}
    obs, interp = OrderflowStatementKind.OBSERVATION, OrderflowStatementKind.INTERPRETATION
    for name in ("point_of_control", "value_area_high", "value_area_low", "initial_balance_high", "initial_balance_low", "poor_high", "poor_low"):
        value = getattr(profile, name)
        if value is not None:
            summary[name] = str(value)
    if profile.naked_pocs:
        summary["naked_pocs"] = [str(item) for item in profile.naked_pocs]
    if last_price is None:
        return tuple(statements), summary, ("last_price_for_profile",)
    vah, val = profile.value_area_high, profile.value_area_low
    if vah is not None and val is not None:
        location = "ABOVE_VALUE" if last_price > vah else "BELOW_VALUE" if last_price < val else "INSIDE_VALUE"
        summary["price_location"] = location
        statements.append(_statement(obs, f"price_{location.lower()} val={val} vah={vah}", ("volume_profile",)))
        if location == "INSIDE_VALUE" and profile.point_of_control is not None:
            statements.append(_statement(interp, "price_rotating_inside_value_poc_magnet", ("volume_profile",), "0.5"))
    ib_high, ib_low = profile.initial_balance_high, profile.initial_balance_low
    if ib_high is not None and ib_low is not None:
        ib = "ABOVE_IB" if last_price > ib_high else "BELOW_IB" if last_price < ib_low else "INSIDE_IB"
        summary["ib_location"] = ib
        statements.append(_statement(obs, f"price_{ib.lower()} ib_low={ib_low} ib_high={ib_high}", ("tpo",)))
        if ib != "INSIDE_IB":
            statements.append(_statement(interp, f"initial_balance_extension_{'up' if ib == 'ABOVE_IB' else 'down'}", ("tpo",), "0.5"))
    for name in ("poor_high", "poor_low"):
        value = getattr(profile, name)
        if value is not None:
            direction = "above" if value > last_price else "below" if value < last_price else "at_price"
            statements.append(_statement(obs, f"{name}_unfinished_auction_at={value} level_{direction}_price", ("tpo",)))
    if profile.naked_pocs:
        nearest = min(profile.naked_pocs, key=lambda item: (abs(item - last_price), item))
        summary["nearest_naked_poc"] = str(nearest)
        statements.append(_statement(obs, f"nearest_naked_poc={nearest}", ("tpo",)))
    return tuple(statements), summary, ()


GAMMA_NEAR = Decimal("0.003")  # within 0.3 % of the flip counts as AT_FLIP


def interpret_gamma(gamma: GammaContext | None, last_price: Decimal | None) -> tuple[tuple[OrderflowStatement, ...], dict[str, Any]]:
    """Where price trades relative to the options gamma levels. Context only: no score hint."""
    if gamma is None:
        return (), {}
    obs, interp, hyp = OrderflowStatementKind.OBSERVATION, OrderflowStatementKind.INTERPRETATION, OrderflowStatementKind.HYPOTHESIS
    summary: dict[str, Any] = {"source": gamma.source, "as_of": None if gamma.as_of is None else gamma.as_of.isoformat(),
                               "assumption": "dealers_long_calls_short_puts"}
    for name in ("gamma_flip", "call_wall", "put_wall", "max_pain", "net_gex", "expected_move_low", "expected_move_high"):
        value = getattr(gamma, name)
        if value is not None:
            summary[name] = str(value)
    statements: list[OrderflowStatement] = []
    if gamma.net_gex is not None:
        regime = "POSITIVE_GAMMA" if gamma.net_gex > ZERO else "NEGATIVE_GAMMA" if gamma.net_gex < ZERO else "NEUTRAL_GAMMA"
        summary["regime"] = regime
        statements.append(_statement(obs, f"options_net_gex={gamma.net_gex} regime={regime}", ("gamma",)))
    if last_price is None:
        return tuple(statements), summary
    flip = gamma.gamma_flip
    if flip is not None:
        distance = (last_price - flip) / flip
        location = "AT_FLIP" if abs(distance) <= GAMMA_NEAR else "ABOVE_FLIP" if distance > ZERO else "BELOW_FLIP"
        summary["price_vs_flip"] = location
        statements.append(_statement(obs, f"price_{location.lower()} gamma_flip={flip}", ("gamma",)))
        if location == "ABOVE_FLIP":
            statements.append(_statement(interp, "above_gamma_flip_dealer_hedging_dampens_moves", ("gamma",), "0.4"))
        elif location == "BELOW_FLIP":
            statements.append(_statement(interp, "below_gamma_flip_dealer_hedging_amplifies_moves", ("gamma",), "0.4"))
        else:
            statements.append(_statement(hyp, "at_gamma_flip_regime_can_switch", ("gamma",), "0.3"))
    if gamma.call_wall is not None and gamma.call_wall > last_price:
        statements.append(_statement(obs, f"call_wall_above_price={gamma.call_wall}", ("gamma",)))
    if gamma.put_wall is not None and gamma.put_wall < last_price:
        statements.append(_statement(obs, f"put_wall_below_price={gamma.put_wall}", ("gamma",)))
    low, high = gamma.expected_move_low, gamma.expected_move_high
    if low is not None and high is not None:
        band = "OUTSIDE_EXPECTED_MOVE" if last_price > high or last_price < low else "INSIDE_EXPECTED_MOVE"
        summary["expected_move_location"] = band
        statements.append(_statement(obs, f"price_{band.lower()} low={low} high={high}", ("gamma",)))
    return tuple(statements), summary
