"""Base adapter types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..positioning import PositioningInputs, ProfileLevels


@dataclass(frozen=True, slots=True)
class AdapterInput:
    """Fully parsed provider input. `structured` distinguishes parsed exports
    from screenshot-derived data; `estimated_prices` lists any price that was
    read only approximately."""

    symbol: str
    venue: str
    market_type: str
    timeframe: str
    observed_at: datetime
    candles: tuple[dict[str, Any], ...]
    trades: tuple[dict[str, Any], ...] = ()
    price_now: Decimal | None = None
    price_timestamp: datetime | None = None
    net_delta: Decimal | None = None
    aggressive_buy_volume: Decimal | None = None
    aggressive_sell_volume: Decimal | None = None
    total_volume: Decimal | None = None
    open_interest_trend: str | None = None
    open_interest_with_price: str | None = None
    delta_divergence: bool | None = None
    volume_bubbles: tuple[str, ...] = ()
    levels: dict[str, Decimal] | None = None
    structured: bool = True
    screenshot_confidence: float | None = None
    estimated_prices: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    extra_notes: tuple[str, ...] = ()
    # Funding, liquidations, OI series, orderbook depth; volume profile / TPO (see positioning.py).
    positioning: PositioningInputs | None = None
    profile: ProfileLevels | None = None


@dataclass(frozen=True, slots=True)
class ListPathEntry:
    path: str  # relative path of the source artifact
    content_hash: str
    adapter_kind: str
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class AdapterResult:
    """What an adapter extracted from a provider input.

    The adapter never `transforms` data into guarantees beyond what it could
    read. `adapter_note` documents provider limitations."""

    adapter_kind: str
    input: AdapterInput
    adapter_note: str = ""
    total_artifacts: int = 0
    parsed_artifacts: int = 0
    skipped_artifacts: int = 0