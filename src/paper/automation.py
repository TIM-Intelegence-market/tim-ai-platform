from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from src.research.case_engine import ResearchCase


@dataclass(frozen=True, slots=True)
class PaperPolicy:
    policy_id: str
    enabled: bool = False
    test_only: bool = True
    evaluation_delay: timedelta = timedelta(minutes=15)
    fee_bps: float = 6.0
    slippage_bps: float = 2.0

    def __post_init__(self) -> None:
        if self.fee_bps <= 0 or self.slippage_bps <= 0:
            raise ValueError("Paper fees and slippage must be positive")
        if not self.test_only:
            raise ValueError("V1 paper automation is TEST_ONLY")


@dataclass(frozen=True, slots=True)
class PaperJournalEntry:
    journal_id: str
    case_id: str
    policy_id: str
    observed_at: datetime
    evaluated_at: datetime
    hypothetical_reference_start: float
    hypothetical_reference_end: float
    gross_change_fraction: float
    fee_fraction: float
    slippage_fraction: float
    net_change_fraction: float
    provenance: str = "TEST_ONLY_PAPER_RESEARCH"
    limitation: str = "Hypothetical evaluation only; not an order, fill, signal, or profitability claim."


class PaperAutomation:
    """Explicit TEST_ONLY case evaluation. It has no exchange or order interface."""

    def __init__(self, policy: PaperPolicy) -> None:
        self.policy = policy
        self.entries: dict[str, PaperJournalEntry] = {}

    def evaluate_case(self, case: ResearchCase, evaluated_at: datetime, start_price: float, end_price: float) -> PaperJournalEntry:
        if not self.policy.enabled:
            raise PermissionError("Paper policy is disabled")
        if case.status != "CLOSED" or case.outcome is None:
            raise ValueError("Research case must be closed with a documented outcome")
        if evaluated_at < case.updated_at + self.policy.evaluation_delay:
            raise ValueError("Evaluation delay has not elapsed")
        if start_price <= 0 or end_price <= 0:
            raise ValueError("Reference prices must be positive")
        identity = f"{case.case_id}|{self.policy.policy_id}|{evaluated_at.isoformat()}"
        journal_id = "paper_" + hashlib.sha256(identity.encode()).hexdigest()[:20]
        if journal_id in self.entries:
            return self.entries[journal_id]
        gross = end_price / start_price - 1
        fees = self.policy.fee_bps * 2 / 10_000
        slippage = self.policy.slippage_bps * 2 / 10_000
        entry = PaperJournalEntry(journal_id, case.case_id, self.policy.policy_id, case.opened_at, evaluated_at, start_price, end_price, gross, fees, slippage, gross - fees - slippage)
        self.entries[journal_id] = entry
        return entry
