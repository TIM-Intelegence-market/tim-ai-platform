"""Cost check of plan-journal plans: estimated roundtrip costs in R, display only.

A plan whose estimated roundtrip costs exceed COST_LIMIT_R is marked
NOT_TRADABLE_COST. The mark is information on the page and in the JSON view
only: it is never written to the journal or its event log and it changes no
entry, stop, target, grade, evidence, journal decision or execution status.

The 0.25 R limit is a hypothesis (Uzi, 24.10.2026). Whether it is a good
limit is to be checked later on backtests and paper trades.

Estimate: the loss case of a plan, filled at its entry and stopped out at its
stop. The cost model is the one the journal books with (research protocol
1.1 via plan_journal.costs_r): fee and slippage on the entry price, fee and
stop slippage on the stop price. Fees are charged on the notional at each
side's own price, so LONG and SHORT use the same formula with their own
prices. Nothing here re-implements the cost rates.

    cost_r   = (fee + slippage in price) / |entry - stop|, 4 decimals
    cost_bps = (fee + slippage in price) / entry * 10 000, 2 decimals

Missing or invalid data gives COST_UNKNOWN, never COST_WITHIN_LIMIT.
Exactly 0.25 R is within the limit; the limit is applied to the 4-decimal
cost_r that is shown.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from src.dashboard.plan_journal import COST_MODEL_VERSION, costs_r

COST_LIMIT_R = 0.25
COST_CHECK_VERSION = "cost_check/1"
COST_WITHIN_LIMIT = "COST_WITHIN_LIMIT"
NOT_TRADABLE_COST = "NOT_TRADABLE_COST"
COST_UNKNOWN = "COST_UNKNOWN"
COST_BASIS = "ROUNDTRIP_ENTRY_TO_STOP"
STATUSES = (COST_WITHIN_LIMIT, NOT_TRADABLE_COST, COST_UNKNOWN)
_EPSILON = 1e-9


def _price(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _unknown(reason: str) -> dict[str, Any]:
    return {"cost_r": None, "cost_bps": None, "cost_status": COST_UNKNOWN, "cost_reason": reason,
            "cost_limit_r": COST_LIMIT_R, "cost_basis": COST_BASIS, "cost_model_version": COST_MODEL_VERSION,
            "cost_check_version": COST_CHECK_VERSION, "informational_only": True}


def classify(cost_r: Any) -> str:
    """Status for a cost in R. Exactly COST_LIMIT_R is within the limit."""
    if isinstance(cost_r, bool) or not isinstance(cost_r, (int, float)) or not math.isfinite(cost_r) or cost_r < 0:
        return COST_UNKNOWN
    return COST_WITHIN_LIMIT if cost_r <= COST_LIMIT_R + _EPSILON else NOT_TRADABLE_COST


def cost_check(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Estimated roundtrip costs of one plan or journal entry (display only)."""
    direction = plan.get("direction")
    if direction not in {"LONG", "SHORT"}:
        return _unknown("direction_unknown")
    entry, stop = _price(plan.get("entry")), _price(plan.get("stop"))
    if entry is None:
        return _unknown("entry_invalid")
    if stop is None:
        return _unknown("stop_invalid")
    if entry == stop:
        return _unknown("stop_distance_zero")
    if (direction == "LONG" and stop > entry) or (direction == "SHORT" and stop < entry):
        return _unknown("stop_on_wrong_side")
    risk = abs(entry - stop)
    # The journal's own cost function for a stop-out right after the fill: no thirds booked.
    fee_r, slippage_r = costs_r({"entry": entry, "stop": stop, "fill_price": entry, "tp_hits": [], "targets": []}, stop, "STOP")
    cost_r = round(fee_r + slippage_r, 4)
    cost_bps = round(cost_r * risk / entry * 10_000, 2)
    status = classify(cost_r)
    return {"cost_r": cost_r, "cost_bps": cost_bps, "cost_status": status, "cost_reason": None if status != COST_UNKNOWN else "cost_invalid",
            "fee_r_estimate": fee_r, "slippage_r_estimate": slippage_r,
            "cost_limit_r": COST_LIMIT_R, "cost_basis": COST_BASIS, "cost_model_version": COST_MODEL_VERSION,
            "cost_check_version": COST_CHECK_VERSION, "informational_only": True}


def cost_summary(journal: Mapping[str, Any]) -> dict[str, Any]:
    """Counts of the cost statuses over all plans of a journal."""
    counts = {status: 0 for status in STATUSES}
    for entry in journal.get("entries") or []:
        counts[cost_check(entry)["cost_status"]] += 1
    return {"limit_r": COST_LIMIT_R, "basis": COST_BASIS, "version": COST_CHECK_VERSION, "informational_only": True,
            "plans": sum(counts.values()), **{status.lower(): count for status, count in counts.items()}}


def with_cost_check(journal: Mapping[str, Any]) -> dict[str, Any]:
    """A copy of a journal view with a cost_check per entry and a cost_check_summary.

    The journal itself is not changed; the result is for display and the JSON API only."""
    view = dict(journal)
    view["entries"] = [{**dict(entry), "cost_check": cost_check(entry)} for entry in journal.get("entries") or []]
    view["cost_check_summary"] = cost_summary(journal)
    return view
