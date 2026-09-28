"""Backtest and calibration foundation.

A forward-only replay harness for calibrating scenario probabilities and
trade grading. It enforces no look-ahead: features for a decision at time t are
computed only from data available strictly before t. All Hypothetical results
are provisional and MUST NOT be claimed as a profitable strategy without
out-of-sample proof on a separate test period.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Callable, Sequence

from .domain import Direction, ProbabilityType
from .version import MODULE_VERSION

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ReplayBar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class ScenarioVerdict:
    scenario_lead: bool
    hit: bool
    direction: Direction
    realized_r: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_lead": self.scenario_lead,
            "hit": self.hit,
            "direction": self.direction.value,
            "realized_r": str(self.realized_r) if self.realized_r is not None else None,
        }


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    scenario_type: str
    n_observed: int
    n_hits: int
    empirical_hit_rate: Decimal  # fraction of observed forward windows that hit
    method: str
    note: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_type": self.scenario_type,
            "n_observed": self.n_observed,
            "n_hits": self.n_hits,
            "empirical_hit_rate": str(self.empirical_hit_rate),
            "method": self.method,
            "note": self.note,
        }


class ForwardOnlyReplay:
    """Deterministic replay that only ever uses `past` bars for a decision."""

    def __init__(self, entry_fraction: Decimal = Decimal("0.001"), target_r: Decimal = Decimal("1.0")) -> None:
        if entry_fraction <= 0 or target_r <= 0:
            raise ValueError("entry_fraction and target_r must be positive")
        self.entry_fraction = entry_fraction
        self.target_r = target_r

    @staticmethod
    def _hit(lead: ReplayBar, reach_target: Decimal, reach_stop: Decimal, direction: Direction) -> tuple[bool, Decimal | None]:
        if direction == Direction.LONG:
            target = lead.close * (Decimal("1") + reach_target)
            stop = lead.close * (Decimal("1") - reach_stop)
            hi, lo = lead.high, lead.low
            if hi >= target and lo <= stop:
                return False, Decimal("-1")  # stop before target inside same bar: conservative loss
            if hi >= target:
                return True, Decimal("1")
            if lo <= stop:
                return False, Decimal("-1")
            return True, (lead.close - lead.open) / lead.open if lead.open > 0 else None
        target = lead.close * (Decimal("1") - reach_target)
        stop = lead.close * (Decimal("1") + reach_stop)
        hi, lo = lead.high, lead.low
        if lo <= target and hi >= stop:
            return False, Decimal("-1")
        if lo <= target:
            return True, Decimal("1")
        if hi >= stop:
            return False, Decimal("-1")
        return True, (lead.open - lead.close) / lead.open if lead.open > 0 else None

    def lead_bars(self, bars: Sequence[ReplayBar]) -> list[ReplayBar]:
        # Bar at index i becomes a lead bar only if past bars decide a scenario.
        return list(bars[:-1])

    def evaluate(
        self,
        bars: Sequence[ReplayBar],
        scenario: Callable[[Sequence[ReplayBar]], bool],
        *,
        reach_target: Decimal = Decimal("0.01"),
        reach_stop: Decimal = Decimal("0.005"),
        direction: Direction = Direction.LONG,
    ) -> ScenarioVerdict:
        if len(bars) < 3:
            return ScenarioVerdict(scenario_lead=False, hit=False, direction=direction)
        # Decides on `bars[:-1]` only (no look-ahead on final bar outcome).
        lead = scenario(bars[:-1])
        if not lead:
            return ScenarioVerdict(scenario_lead=False, hit=False, direction=direction)
        hit, r = self._hit(bars[-1], reach_target, reach_stop, direction)
        return ScenarioVerdict(scenario_lead=True, hit=hit, direction=direction, realized_r=r)


def compute_calibration(verdicts: Sequence[ScenarioVerdict], scenario_type: str) -> CalibrationResult:
    n = len(verdicts)
    hits = sum(1 for v in verdicts if v.scenario_lead and v.hit)
    observed = sum(1 for v in verdicts if v.scenario_lead)
    rate = Decimal(hits) / Decimal(observed) if observed else ZERO
    return CalibrationResult(
        scenario_type=scenario_type,
        n_observed=observed,
        n_hits=hits,
        empirical_hit_rate=rate,
        method="forward_only_replay",
        note="Provisional; requires out-of-sample test period before any calibration claim.",
    )