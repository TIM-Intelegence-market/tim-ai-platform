from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    price: float
    quantity: float
    event_time: datetime
    trade_id: int | None = None
    buyer_is_maker: bool | None = None

    def __post_init__(self) -> None:
        if self.price <= 0 or self.quantity <= 0:
            raise ValueError("Trade price and quantity must be positive")
        if self.event_time.tzinfo is None:
            raise ValueError("Trade event_time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    trade_count: int
    closed: bool = True

    def __post_init__(self) -> None:
        if self.open_time.tzinfo is None or self.close_time.tzinfo is None:
            raise ValueError("Candle timestamps must be timezone-aware")
        if self.close_time <= self.open_time:
            raise ValueError("Candle close_time must be after open_time")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close) or self.low > self.high:
            raise ValueError("Invalid OHLC relationship")
        if self.volume < 0 or self.trade_count < 0:
            raise ValueError("Volume and trade_count cannot be negative")


class ObservationKind(StrEnum):
    BOS_BULLISH = "BOS_BULLISH"
    BOS_BEARISH = "BOS_BEARISH"
    REJECTION = "REJECTION"
    FAILED_CONTINUATION = "FAILED_CONTINUATION"
    WEAK_CONTINUATION = "WEAK_CONTINUATION"
    ABSORPTION_CONTEXT = "ABSORPTION_CONTEXT"


@dataclass(frozen=True, slots=True)
class Setup:
    setup_id: str
    name: str
    enabled: bool = False
    required_observations: tuple[ObservationKind, ...] = ()
    description: str = ""


@dataclass(slots=True)
class Observation:
    kind: ObservationKind
    symbol: str
    timeframe: str
    observed_at: datetime
    summary: str
    confidence: int
    evidence: dict[str, Any]
    source: str = "deterministic_rules"
    provenance: str = "PUBLIC_MARKET_DATA"
    observation_version: int = 1
    rule_id: str = "unassigned"
    rule_version: str = "1.0.0"
    input_hash: str = ""
    observation_id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 100:
            raise ValueError("Observation confidence must be between 0 and 100")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["kind"] = self.kind.value
        result["observation_id"] = str(self.observation_id)
        result["observed_at"] = self.observed_at.isoformat()
        result["created_at"] = self.created_at.isoformat()
        return result
