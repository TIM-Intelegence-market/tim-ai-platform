"""Paper and shadow trade journal.

A research-only journal that records trade plans, their evaluation, and their
hypothetical outcomes. It is a journal, not an execution system: it cannot
place orders, it holds no API keys, and it never touches an exchange. Fees and
slippage are always modelled from the configured fee model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from ..config import MAX_LEVERAGE
from ..domain import TradePlan, TradeStatus, utc_now
from ..version import MODULE_VERSION

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class PaperExecutionInput:
    plan: TradePlan
    fill_price: Decimal
    exit_price: Decimal | None = None
    outcome_fraction: Decimal | None = None  # realized PnL fraction of entry notional
    fee_bps: Decimal = Decimal("6")
    slippage_bps: Decimal = Decimal("2")
    observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.fill_price <= ZERO:
            raise ValueError("fill_price must be positive")
        if self.exit_price is not None and self.exit_price <= ZERO:
            raise ValueError("exit_price must be positive")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("fees and slippage cannot be negative")


@dataclass(frozen=True, slots=True)
class PaperExecutionRecord:
    record_id: str
    plan: TradePlan
    fill_price: Decimal
    exit_price: Decimal | None
    gross_fraction: Decimal
    fee_fraction: Decimal
    slippage_fraction: Decimal
    net_fraction: Decimal
    rule_violations: tuple[str, ...]
    provenance: str
    limitation: str
    created_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "plan_id": self.plan.trade_id,
            "scenario_id": self.plan.scenario_id,
            "direction": self.plan.direction.value,
            "fill_price": str(self.fill_price),
            "exit_price": str(self.exit_price) if self.exit_price is not None else None,
            "gross_fraction": str(self.gross_fraction),
            "fee_fraction": str(self.fee_fraction),
            "slippage_fraction": str(self.slippage_fraction),
            "net_fraction": str(self.net_fraction),
            "rule_violations": list(self.rule_violations),
            "provenance": self.provenance,
            "limitation": self.limitation,
            "created_at": self.created_at.isoformat(),
            "live_execution": False,
        }


class PaperExecutionJournal:
    """Stores paper/shadow records in memory. Never submits orders."""

    def __init__(self) -> None:
        self._records: list[PaperExecutionRecord] = []
        self.module_version = MODULE_VERSION

    def record(self, entry: PaperExecutionInput) -> PaperExecutionRecord:
        notional = entry.fill_price
        fee_fraction = entry.fee_bps / Decimal("10000")
        slippage_fraction = entry.slippage_bps / Decimal("10000")
        if entry.outcome_fraction is not None:
            gross_fraction = entry.outcome_fraction
        elif entry.exit_price is not None:
            if entry.plan.direction.value == "LONG":
                gross_fraction = (entry.exit_price - entry.fill_price) / notional
            else:
                gross_fraction = (entry.fill_price - entry.exit_price) / notional
        else:
            gross_fraction = ZERO
        net_fraction = gross_fraction - fee_fraction - slippage_fraction
        violations = self._check_rules(entry)
        record_id = f"ppr_{utc_now().strftime('%Y%m%d%H%M%S%f')}_{len(self._records)}"
        record = PaperExecutionRecord(
            record_id=record_id,
            plan=entry.plan,
            fill_price=entry.fill_price,
            exit_price=entry.exit_price,
            gross_fraction=gross_fraction,
            fee_fraction=fee_fraction,
            slippage_fraction=slippage_fraction,
            net_fraction=net_fraction,
            rule_violations=violations,
            provenance="TEST_ONLY_PAPER_RESEARCH",
            limitation="Hypothetical evaluation only; not an order, fill, signal, or profitability claim.",
            created_at=entry.observed_at or utc_now(),
        )
        self._records.append(record)
        return record

    def _check_rules(self, entry: PaperExecutionInput) -> tuple[str, ...]:
        violations: list[str] = []
        if entry.plan.leverage > MAX_LEVERAGE:
            violations.append("leverage_exceeds_max_10x")
        if entry.plan.execution_sensitivity.value == "HIGH" and entry.plan.vetting_mode.value != "SHADOW":
            violations.append("high_execution_sensitivity_requires_shadow")
        if entry.fill_price < (entry.plan.entry_zone_low or ZERO):
            violations.append("fill_below_entry_zone")
        if entry.fill_price > (entry.plan.entry_zone_high or entry.plan.trigger):
            violations.append("fill_above_entry_zone")
        return tuple(violations)

    def records(self) -> tuple[PaperExecutionRecord, ...]:
        return tuple(self._records)

    def clear(self) -> None:
        self._records.clear()