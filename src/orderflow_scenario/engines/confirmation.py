"""Confirmation State Machine.

A scenario may only reach CONFIRMED when every mandatory confirmation is met.
The state machine is PROPOSED -> WATCHING -> PARTIALLY_CONFIRMED -> CONFIRMED,
or PROPOSED -> INVALIDATED / EXPIRED. Confirmations and invalidations are
provided as deterministic observations; this engine only advances state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..domain import ConfirmationState, Scenario, ScenarioConfirmationState, utc_now


@dataclass(frozen=True, slots=True)
class ConfirmationUpdate:
    scenario_id: str
    fulfilled_mandatory: tuple[str, ...]
    fulfilled_optional: tuple[str, ...]
    invalidations: tuple[str, ...]
    expired_reason: str | None = None
    observed_at: datetime | None = None


class ConfirmationEngine:
    """Advances a scenario along its confirmation state machine."""

    def apply(self, scenario: Scenario, update: ConfirmationUpdate) -> Scenario:
        new_state, mandatory_pending = self._next_state(scenario, update)
        confirmation = ScenarioConfirmationState(
            state=new_state,
            mandatory_fulfilled=tuple(update.fulfilled_mandatory),
            mandatory_pending=mandatory_pending,
            optional_fulfilled=tuple(update.fulfilled_optional),
            invalidation_triggered=tuple(update.invalidations),
            expired_reason=update.expired_reason,
            updated_at=update.observed_at or utc_now(),
        )
        return scenario.with_confirmation(confirmation)

    def _next_state(self, scenario: Scenario, update: ConfirmationUpdate) -> tuple[ConfirmationState, tuple[str, ...]]:
        mandated = scenario.mandatory_confirmations
        fulfilled = update.fulfilled_mandatory
        invalidation_still = [cond for cond in update.invalidations if cond in scenario.invalidation]
        has_specific_invalidation = any(cond in scenario.invalidation for cond in update.invalidations)

        if update.expired_reason:
            return ConfirmationState.EXPIRED, tuple(m for m in mandated if m not in fulfilled)
        if has_specific_invalidation:
            return ConfirmationState.INVALIDATED, tuple(m for m in mandated if m not in fulfilled)

        pending = tuple(m for m in mandated if m not in fulfilled)
        if not pending:
            return ConfirmationState.CONFIRMED, ()
        if len(fulfilled) == 0:
            return ConfirmationState.WATCHING, pending
        return ConfirmationState.PARTIALLY_CONFIRMED, pending


# Convenience predicates used by the pipeline / tests to derive updates from market data.
def mandatory_fulfilled_for_breakout(close_above_trigger: bool, retest_holds: bool, constructive: bool, no_fall_back: bool) -> bool:
    return all((close_above_trigger, retest_holds, constructive, no_fall_back))


def mandatory_fulfilled_for_reversal(level_reclaimed: bool, reclaim_holds: bool, no_sustained_progress_below: bool, liquidity_swept: bool, stop_available: bool) -> bool:
    return all((level_reclaimed, reclaim_holds, no_sustained_progress_below, liquidity_swept, stop_available))


def mandatory_fulfilled_for_rejection(return_below: bool, retest_fails: bool, acceptance_above_fails: bool, upper_tested: bool, invalidation_above: bool) -> bool:
    return all((return_below, retest_fails, acceptance_above_fails, upper_tested, invalidation_above))