"""Central portfolio risk limit for paper plans across symbols (deterministic).

Paper only: the result is a decision record, never an order. Limits are
expressed in R (one R = the planned loss of one standard plan) so that symbols
with different prices compare on the same scale.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

ALLOW = "ALLOW"
REJECT = "REJECT"


@dataclass(frozen=True, slots=True)
class PortfolioLimits:
    max_total_open_r: float = 3.0
    max_open_r_per_symbol: float = 1.0
    max_open_plans: int = 3
    # Plans in one direction across all symbols; crypto majors move together,
    # so three longs are close to one large long.
    max_same_direction_r: float = 2.0

    def __post_init__(self) -> None:
        for name in ("max_total_open_r", "max_open_r_per_symbol", "max_same_direction_r"):
            value = getattr(self, name)
            if not value > 0 or value != value or value == float("inf"):
                raise ValueError(f"{name} must be a positive finite number")
        if self.max_open_plans < 1:
            raise ValueError("max_open_plans must be at least 1")


@dataclass(frozen=True, slots=True)
class PaperPlan:
    symbol: str
    direction: str
    risk_r: float

    def __post_init__(self) -> None:
        if self.direction not in {"LONG", "SHORT"}:
            raise ValueError("direction must be LONG or SHORT")
        if not self.risk_r > 0 or self.risk_r != self.risk_r or self.risk_r == float("inf"):
            raise ValueError("risk_r must be a positive finite number")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    status: str
    reasons: tuple[str, ...] = field(default_factory=tuple)
    total_open_r_after: float = 0.0


def evaluate(open_plans: Iterable[PaperPlan], proposed: PaperPlan, limits: PortfolioLimits) -> RiskDecision:
    plans = list(open_plans)
    total = sum(plan.risk_r for plan in plans) + proposed.risk_r
    per_symbol = sum(plan.risk_r for plan in plans if plan.symbol == proposed.symbol) + proposed.risk_r
    same_direction = sum(plan.risk_r for plan in plans if plan.direction == proposed.direction) + proposed.risk_r
    reasons: list[str] = []
    # Small tolerance so 1.0 + 2.0 == 3.0 is not rejected by float noise.
    epsilon = 1e-9
    if len(plans) + 1 > limits.max_open_plans:
        reasons.append("MAX_OPEN_PLANS")
    if total > limits.max_total_open_r + epsilon:
        reasons.append("MAX_TOTAL_OPEN_R")
    if per_symbol > limits.max_open_r_per_symbol + epsilon:
        reasons.append("MAX_OPEN_R_PER_SYMBOL")
    if same_direction > limits.max_same_direction_r + epsilon:
        reasons.append("MAX_SAME_DIRECTION_R")
    return RiskDecision(REJECT if reasons else ALLOW, tuple(reasons), round(total, 9))
