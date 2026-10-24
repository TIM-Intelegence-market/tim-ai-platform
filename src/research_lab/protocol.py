"""Constants fixed by docs/research_lab/PROTOKOLL.md (version 1.1, see its change log).

Changing a value here requires a matching entry in the protocol's change log.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum

PROTOCOL_VERSION = "1.1"


class Split(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    HOLDOUT = "holdout"


def _utc_ms(year: int, month: int, day: int) -> int:
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp() * 1000)


VALIDATION_START_MS = _utc_ms(2023, 1, 1)
HOLDOUT_START_MS = _utc_ms(2025, 1, 1)


def split_of(open_time_ms: int) -> Split:
    if open_time_ms >= HOLDOUT_START_MS:
        return Split.HOLDOUT
    if open_time_ms >= VALIDATION_START_MS:
        return Split.VALIDATION
    return Split.TRAIN


@dataclass(frozen=True, slots=True)
class CostModel:
    """Costs per side as fractions of price (protocol section 4.4)."""

    fee: float = 0.0005
    slippage: float = 0.0003
    stop_slippage: float = 0.0005
    funding_credits_allowed: bool = True

    def __post_init__(self) -> None:
        if min(self.fee, self.slippage, self.stop_slippage) < 0:
            raise ValueError("costs cannot be negative")

    def stressed(self) -> "CostModel":
        return CostModel(self.fee * 2, self.slippage * 2, self.stop_slippage * 2, funding_credits_allowed=False)


# Flat funding cost per 8 h before the perpetual existed (Long horizon only).
PRE_PERP_FUNDING = 0.0001
PRE_PERP_FUNDING_STRESS = 0.0002
FUNDING_INTERVAL_MS = 8 * 3_600_000

BASE_COSTS = CostModel()
STRESS_COSTS = BASE_COSTS.stressed()

# Fixed-fractional measuring convention for drawdown (section 4.3), not a sizing advice.
RISK_PER_TRADE = 0.01
MAX_DRAWDOWN_LIMIT = 0.20

MIN_TRADES_TRAIN = {"short": 500, "mid": 50, "long": 20}
MIN_TRADES_HOLDOUT = {"short": 200, "mid": 30, "long": 10}
FAMILY_ALPHA = 0.05
RANDOM_RUNS = 10_000
MAX_REGISTER_ENTRIES = 60
