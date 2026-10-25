"""Exchange filters per symbol (tick size, lot step, minimum notional).

Values are a dated snapshot of the public Binance spot ``exchangeInfo``; a run
that needs current values parses a fresh payload with ``parse_exchange_info``.
Decimal arithmetic avoids float rounding at tick boundaries.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class InstrumentSpec:
    symbol: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    min_notional: Decimal
    as_of: str

    def __post_init__(self) -> None:
        for name in ("tick_size", "step_size", "min_qty", "min_notional"):
            value = getattr(self, name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{self.symbol}: {name} must be a positive Decimal")

    def round_price(self, price: Decimal) -> Decimal:
        """Nearest valid price on the tick grid (half-even at the exact midpoint)."""
        _positive(price, "price")
        ticks = (price / self.tick_size).to_integral_value(rounding=ROUND_HALF_EVEN)
        return ticks * self.tick_size

    def floor_quantity(self, quantity: Decimal) -> Decimal:
        """Largest valid quantity not above ``quantity`` (never rounds risk up)."""
        _positive(quantity, "quantity")
        steps = (quantity / self.step_size).to_integral_value(rounding=ROUND_DOWN)
        return steps * self.step_size

    def check_order_size(self, price: Decimal, quantity: Decimal) -> tuple[bool, str]:
        """Paper check only: does a size satisfy lot step, min qty and min notional?"""
        _positive(price, "price")
        _positive(quantity, "quantity")
        if quantity % self.step_size != 0:
            return False, "QTY_NOT_ON_STEP"
        if quantity < self.min_qty:
            return False, "QTY_BELOW_MIN"
        if price * quantity < self.min_notional:
            return False, "NOTIONAL_BELOW_MIN"
        return True, "OK"


def _positive(value: Decimal, name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{name} must be a positive finite Decimal")


def parse_exchange_info(payload: Mapping[str, Any], *, as_of: str) -> dict[str, InstrumentSpec]:
    """Build specs from a Binance ``/api/v3/exchangeInfo`` payload; fail closed on missing filters."""
    specs: dict[str, InstrumentSpec] = {}
    for item in payload.get("symbols", []):
        symbol = str(item["symbol"]).upper()
        filters = {entry["filterType"]: entry for entry in item.get("filters", [])}
        notional = filters.get("NOTIONAL") or filters.get("MIN_NOTIONAL")
        if "PRICE_FILTER" not in filters or "LOT_SIZE" not in filters or notional is None:
            raise ValueError(f"{symbol}: exchange filters incomplete")
        specs[symbol] = InstrumentSpec(
            symbol=symbol,
            tick_size=Decimal(filters["PRICE_FILTER"]["tickSize"]),
            step_size=Decimal(filters["LOT_SIZE"]["stepSize"]),
            min_qty=Decimal(filters["LOT_SIZE"]["minQty"]),
            min_notional=Decimal(notional["minNotional"]),
            as_of=as_of,
        )
    return specs


# Snapshot read on the Mac from api.binance.com on 2026-10-25 01:39 local time.
SNAPSHOT_AS_OF = "2026-10-24T23:39:58Z"
SNAPSHOT_SPECS: dict[str, InstrumentSpec] = {
    symbol: InstrumentSpec(symbol, Decimal("0.01"), Decimal(step), Decimal(step), Decimal("5"), SNAPSHOT_AS_OF)
    for symbol, step in (("BTCUSDT", "0.00001"), ("ETHUSDT", "0.0001"), ("SOLUSDT", "0.001"))
}
