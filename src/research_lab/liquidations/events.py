"""Reported liquidation events from Binance USD-M ``forceOrder`` and Bybit V5 ``allLiquidation``.

Side convention (pre-registration S12, section 3.1), always as the side of the liquidated
position, which is the side of the heatmap cell:

- Binance: a forced SELL closes a long -> ``long``; a forced BUY closes a short -> ``short``.
  Price ``ap`` (average fill), quantity ``z`` (filled), time ``T``. Only ``X = FILLED`` counts.
- Bybit: ``S = Buy`` means a long position was liquidated -> ``long``; ``Sell`` -> ``short``.
  Price ``p`` (bankruptcy price), quantity ``v``, time ``T``.

Both conventions must be confirmed with one real event per venue before version 1.0
(section 9); ``LiquidationEvent.raw_side`` keeps the venue's own field for that check.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

BINANCE = "binance"
BYBIT = "bybit"
LONG = "long"
SHORT = "short"


class EventFormatError(ValueError):
    """A message on the liquidation stream does not have the documented shape."""


@dataclass(frozen=True)
class LiquidationEvent:
    venue: str
    symbol: str
    side: str  # side of the liquidated position: "long" or "short"
    raw_side: str
    price: Decimal
    quantity: Decimal
    time_ms: int
    status: str  # Binance order status; "FILLED" for Bybit (stream reports executions)

    @property
    def notional(self) -> Decimal:
        return self.price * self.quantity

    @property
    def counts(self) -> bool:
        """Only filled Binance orders count (section 3.1); Bybit entries always count."""
        return self.status == "FILLED"

    @property
    def key(self) -> tuple[str, str, str, int, str, str]:
        """Duplicate key: same venue, symbol, side, time, price and quantity count once."""
        return (self.venue, self.symbol, self.raw_side, self.time_ms, str(self.price), str(self.quantity))


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, str):
        raise EventFormatError(f"{field}: expected a decimal string, got {type(value).__name__}")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise EventFormatError(f"{field}: not a decimal: {value!r}") from exc
    if not number.is_finite() or number < 0:
        raise EventFormatError(f"{field}: invalid value {value!r}")
    return number


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EventFormatError(f"{field}: expected an integer")
    return value


def parse_binance(message: Mapping[str, Any]) -> list[LiquidationEvent]:
    """One ``forceOrder`` message (raw or combined-stream wrapper) -> one event.

    Returns an empty list for messages that are not liquidation events (e.g. a
    subscription answer ``{"result": null, "id": 1}``).
    """
    if "data" in message and isinstance(message["data"], Mapping):
        message = message["data"]
    if message.get("e") != "forceOrder":
        if "result" in message and "id" in message:
            return []
        raise EventFormatError(f"binance: unexpected event type {message.get('e')!r}")
    order = message.get("o")
    if not isinstance(order, Mapping):
        raise EventFormatError("binance: missing order object 'o'")
    raw_side = order.get("S")
    if raw_side == "SELL":
        side = LONG
    elif raw_side == "BUY":
        side = SHORT
    else:
        raise EventFormatError(f"binance: unknown side {raw_side!r}")
    symbol = order.get("s")
    status = order.get("X")
    if not isinstance(symbol, str) or not isinstance(status, str):
        raise EventFormatError("binance: symbol or status missing")
    return [LiquidationEvent(venue=BINANCE, symbol=symbol, side=side, raw_side=raw_side,
                             price=_decimal(order.get("ap"), "ap"), quantity=_decimal(order.get("z"), "z"),
                             time_ms=_int(order.get("T"), "T"), status=status)]


def parse_bybit(message: Mapping[str, Any]) -> list[LiquidationEvent]:
    """One ``allLiquidation.<symbol>`` push -> its events.

    Control messages (subscribe answers, pongs with ``op``) give an empty list.
    """
    if "op" in message or ("success" in message and "topic" not in message):
        return []
    topic = message.get("topic")
    if not isinstance(topic, str) or not topic.startswith("allLiquidation."):
        raise EventFormatError(f"bybit: unexpected topic {topic!r}")
    data = message.get("data")
    if not isinstance(data, list):
        raise EventFormatError("bybit: 'data' is not a list")
    events = []
    for row in data:
        if not isinstance(row, Mapping):
            raise EventFormatError("bybit: data row is not an object")
        raw_side = row.get("S")
        if raw_side == "Buy":
            side = LONG
        elif raw_side == "Sell":
            side = SHORT
        else:
            raise EventFormatError(f"bybit: unknown side {raw_side!r}")
        symbol = row.get("s")
        if not isinstance(symbol, str):
            raise EventFormatError("bybit: symbol missing")
        events.append(LiquidationEvent(venue=BYBIT, symbol=symbol, side=side, raw_side=raw_side,
                                       price=_decimal(row.get("p"), "p"), quantity=_decimal(row.get("v"), "v"),
                                       time_ms=_int(row.get("T"), "T"), status="FILLED"))
    return events


PARSERS = {BINANCE: parse_binance, BYBIT: parse_bybit}


def dedupe(events: list[LiquidationEvent]) -> list[LiquidationEvent]:
    """Keep the first of identical events (section 3.1), order preserved."""
    seen: set[tuple[str, str, str, int, str, str]] = set()
    result = []
    for event in events:
        if event.key in seen:
            continue
        seen.add(event.key)
        result.append(event)
    return result
