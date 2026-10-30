"""Typed domain model for the Orderflow Scenario and Trade Decision Manager.

All timestamps are timezone-aware. All monetary and positional values are
`Decimal` to avoid floating-point drift in risk arithmetic. Every value class
is frozen and deterministic; no class here has side effects.

Design rule (see docs/orderflow_scenario): the analysis layer proposes, the
Risk Engine disposes. Analysis must never mutate state, must never touch any
account, and must never generate orders.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

ZERO = Decimal("0")
EPSILON = Decimal("1e-12")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _decimal(value: int | float | str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    return format(normalized, "f") if normalized != ZERO else "0"


def sha256_hex(payload: dict[str, Any]) -> str:
    """Deterministic content hash for audit inputs."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class Mode(StrEnum):
    """Operational modes. LIVE is intentionally absent: no enum value may map to live order execution."""

    OBSERVE = "OBSERVE"
    RESEARCH = "RESEARCH"
    SIMULATE = "SIMULATE"
    PAPER = "PAPER"
    SHADOW = "SHADOW"


class VettingMode(StrEnum):
    """How a trade candidate is treated for execution simulation."""

    NONE = "NONE"
    PAPER = "PAPER"
    SHADOW = "SHADOW"


class MarketStateKind(StrEnum):
    TREND_UP = "TREND_UP"
    TREND_DOWN = "TREND_DOWN"
    BALANCE = "BALANCE"
    COMPRESSION = "COMPRESSION"
    EXPANSION = "EXPANSION"
    BREAKOUT_ATTEMPT = "BREAKOUT_ATTEMPT"
    BREAKDOWN_ATTEMPT = "BREAKDOWN_ATTEMPT"
    ACCEPTANCE_ABOVE_VALUE = "ACCEPTANCE_ABOVE_VALUE"
    ACCEPTANCE_BELOW_VALUE = "ACCEPTANCE_BELOW_VALUE"
    REJECTION_ABOVE_VALUE = "REJECTION_ABOVE_VALUE"
    REJECTION_BELOW_VALUE = "REJECTION_BELOW_VALUE"
    LIQUIDITY_SWEEP_HIGH = "LIQUIDITY_SWEEP_HIGH"
    LIQUIDITY_SWEEP_LOW = "LIQUIDITY_SWEEP_LOW"
    FAILED_AUCTION_HIGH = "FAILED_AUCTION_HIGH"
    FAILED_AUCTION_LOW = "FAILED_AUCTION_LOW"
    EXHAUSTION = "EXHAUSTION"
    DELEVERAGING = "DELEVERAGING"
    UNCERTAIN = "UNCERTAIN"


class AuctionStateKind(StrEnum):
    BALANCE = "BALANCE"
    IMBALANCE = "IMBALANCE"
    ACCEPTANCE = "ACCEPTANCE"
    REJECTION = "REJECTION"
    VALUE_MIGRATION = "VALUE_MIGRATION"
    FAILED_AUCTION = "FAILED_AUCTION"
    EXCESS = "EXCESS"
    INITIATIVE_ACTIVITY = "INITIATIVE_ACTIVITY"
    RESPONSIVE_ACTIVITY = "RESPONSIVE_ACTIVITY"
    PRICE_DISCOVERY = "PRICE_DISCOVERY"
    RETURN_TO_VALUE = "RETURN_TO_VALUE"
    ROTATION = "ROTATION"
    RANGE_EXTENSION = "RANGE_EXTENSION"


class OrderflowStatementKind(StrEnum):
    """Distinguishes observation from interpretation/hypothesis/confirmation/refutation."""

    OBSERVATION = "OBSERVATION"
    INTERPRETATION = "INTERPRETATION"
    HYPOTHESIS = "HYPOTHESIS"
    CONFIRMATION = "CONFIRMATION"
    REFUTATION = "REFUTATION"


class ScenarioType(StrEnum):
    BREAKOUT_ACCEPTANCE = "BREAKOUT_ACCEPTANCE"
    LIQUIDITY_SWEEP_REVERSAL = "LIQUIDITY_SWEEP_REVERSAL"
    REJECTION_FAILED_BREAKOUT = "REJECTION_FAILED_BREAKOUT"
    BALANCE_ROTATION = "BALANCE_ROTATION"
    TREND_PULLBACK = "TREND_PULLBACK"
    SHORT_SQUEEZE = "SHORT_SQUEEZE"
    LONG_SQUEEZE = "LONG_SQUEEZE"
    DELEVERAGING_MOVE = "DELEVERAGING_MOVE"
    FAILED_AUCTION = "FAILED_AUCTION"
    EXHAUSTION_REVERSAL = "EXHAUSTION_REVERSAL"
    VALUE_REVERSION = "VALUE_REVERSION"
    LVN_TRAVERSAL = "LVN_TRAVERSAL"
    HVN_ROTATION = "HVN_ROTATION"
    OPENING_DRIVE = "OPENING_DRIVE"
    OPENING_REJECTION = "OPENING_REJECTION"
    BREAKOUT_TRAP = "BREAKOUT_TRAP"
    BREAKDOWN_TRAP = "BREAKDOWN_TRAP"


class Direction(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class EntryModel(StrEnum):
    MARKET_AFTER_CONFIRMATION = "MARKET_AFTER_CONFIRMATION"
    LIMIT_RETEST = "LIMIT_RETEST"
    ENTRY_ZONE = "ENTRY_ZONE"
    SPLIT_ENTRY = "SPLIT_ENTRY"
    CONFIRMATION_CLOSE = "CONFIRMATION_CLOSE"
    RECLAIM = "RECLAIM"
    FAILED_RETEST = "FAILED_RETEST"
    PULLBACK = "PULLBACK"
    ACCEPTANCE = "ACCEPTANCE"


class ConfirmationState(StrEnum):
    PROPOSED = "PROPOSED"
    WATCHING = "WATCHING"
    PARTIALLY_CONFIRMED = "PARTIALLY_CONFIRMED"
    CONFIRMED = "CONFIRMED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class ProbabilityType(StrEnum):
    HEURISTIC_SCORE = "HEURISTIC_SCORE"
    UNCALIBRATED_CONFIDENCE = "UNCALIBRATED_CONFIDENCE"
    EMPIRICALLY_CALIBRATED = "EMPIRICALLY_CALIBRATED"
    MODEL_BASED = "MODEL_BASED"


class RiskStatus(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TradeStatus(StrEnum):
    DRAFT = "DRAFT"
    RISK_REJECTED = "RISK_REJECTED"
    PAPER_APPROVED = "PAPER_APPROVED"
    SHADOW_APPROVED = "SHADOW_APPROVED"
    ACTIVE_PAPER = "ACTIVE_PAPER"
    ACTIVE_SHADOW = "ACTIVE_SHADOW"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DecisionStatus(StrEnum):
    NO_TRADE = "NO_TRADE"
    TRADE_PLAN = "TRADE_PLAN"


class ExecutionSensitivity(StrEnum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"


class Grade(StrEnum):
    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Stable market identification for a single analysis."""

    symbol: str
    venue: str
    market_type: str
    timeframe: str
    timestamp: datetime

    def __post_init__(self) -> None:
        if not self.symbol or not self.venue or not self.market_type or not self.timeframe:
            raise ValueError("symbol, venue, market_type, timeframe are required")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class DataQualityReport:
    status: str
    confidence: Decimal
    missing_fields: tuple[str, ...]
    estimated_fields: tuple[str, ...]
    problems: tuple[str, ...]
    schema: str = "OBSERVE"

    def __post_init__(self) -> None:
        if self.status not in {"PASS", "INSUFFICIENT_DATA", "PARTIAL"}:
            raise ValueError(f"invalid status {self.status}")
        if not (ZERO <= self.confidence <= Decimal("1")):
            raise ValueError("confidence must be within [0,1]")

    def passed(self) -> bool:
        return self.status == "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "confidence": _text(self.confidence),
            "missing_fields": list(self.missing_fields),
            "estimated_fields": list(self.estimated_fields),
            "problems": list(self.problems),
        }


@dataclass(frozen=True, slots=True)
class MarketState:
    primary: MarketStateKind
    secondary: tuple[MarketStateKind, ...]
    evidence: tuple[str, ...]
    conflicts: tuple[str, ...]
    confidence: Decimal
    missing_data: tuple[str, ...]
    invalidation_conditions: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (ZERO <= self.confidence <= Decimal("1")):
            raise ValueError("confidence must be within [0,1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.value,
            "secondary": [item.value for item in self.secondary],
            "evidence": list(self.evidence),
            "conflicts": list(self.conflicts),
            "confidence": _text(self.confidence),
            "missing_data": list(self.missing_data),
            "invalidation_conditions": list(self.invalidation_conditions),
        }


@dataclass(frozen=True, slots=True)
class AuctionState:
    primary: AuctionStateKind
    secondary: tuple[AuctionStateKind, ...]
    evidence: tuple[str, ...]
    confidence: Decimal

    def __post_init__(self) -> None:
        if not (ZERO <= self.confidence <= Decimal("1")):
            raise ValueError("confidence must be within [0,1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.value,
            "secondary": [item.value for item in self.secondary],
            "evidence": list(self.evidence),
            "confidence": _text(self.confidence),
        }


@dataclass(frozen=True, slots=True)
class OrderflowStatement:
    """One statement of the orderflow interpretation, explicitly typed."""

    kind: OrderflowStatementKind
    text: str
    evidence_refs: tuple[str, ...] = ()
    weight: Decimal = Decimal("1")

    def __post_init__(self) -> None:
        if not self.text:
            raise ValueError("statement text required")

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "text": self.text, "evidence_refs": list(self.evidence_refs), "weight": _text(self.weight)}


@dataclass(frozen=True, slots=True)
class OrderflowInterpretation:
    aggressive_side: str
    price_response: str
    absorption_hypothesis: str | None
    absorption_confirmed: bool
    open_interest_interpretation: str | None
    statements: tuple[OrderflowStatement, ...]
    confidence: Decimal
    missing_data: tuple[str, ...]
    # Funding, liquidations, OI series, orderbook depth (see positioning.py); empty when not supplied.
    positioning: dict[str, Any] = field(default_factory=dict)
    # Volume profile / TPO reading; empty when not supplied.
    profile: dict[str, Any] = field(default_factory=dict)
    # Options gamma reading (positioning.interpret_gamma); empty when not supplied.
    gamma: dict[str, Any] = field(default_factory=dict)
    # Reaction read: ABSORPTION | EXHAUSTION | CONTINUATION | UNRESOLVED (orderflow_interpretation.py).
    reaction: str = "UNRESOLVED"
    exhaustion_hypothesis: str | None = None  # BUYERS_EXHAUSTED | SELLERS_EXHAUSTED
    exhaustion_confirmed: bool = False
    # Footprint reading of the last bar (footprint.py); empty when no footprint was supplied.
    footprint: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (ZERO <= self.confidence <= Decimal("1")):
            raise ValueError("confidence must be within [0,1]")
        if self.reaction not in {"ABSORPTION", "EXHAUSTION", "CONTINUATION", "UNRESOLVED"}:
            raise ValueError("invalid reaction")
        if self.absorption_hypothesis and self.exhaustion_hypothesis:
            raise ValueError("absorption and exhaustion are mutually exclusive reads")

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggressive_side": self.aggressive_side,
            "price_response": self.price_response,
            "reaction": self.reaction,
            "absorption_hypothesis": self.absorption_hypothesis,
            "absorption_confirmed": self.absorption_confirmed,
            "exhaustion_hypothesis": self.exhaustion_hypothesis,
            "exhaustion_confirmed": self.exhaustion_confirmed,
            "open_interest_interpretation": self.open_interest_interpretation,
            "statements": [item.to_dict() for item in self.statements],
            "confidence": _text(self.confidence),
            "missing_data": list(self.missing_data),
            "positioning": self.positioning,
            "profile": self.profile,
            "gamma": self.gamma,
            "footprint": self.footprint,
        }


@dataclass(frozen=True, slots=True)
class ConfirmationItem:
    label: str
    kind: str  # OBLIGATORY or OPTIONAL
    fulfilled: bool
    note: str = ""


@dataclass(frozen=True, slots=True)
class ScenarioConfirmationState:
    state: ConfirmationState
    mandatory_fulfilled: tuple[str, ...]
    mandatory_pending: tuple[str, ...]
    optional_fulfilled: tuple[str, ...]
    invalidation_triggered: tuple[str, ...]
    expired_reason: str | None = None
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "mandatory_fulfilled": list(self.mandatory_fulfilled),
            "mandatory_pending": list(self.mandatory_pending),
            "optional_fulfilled": list(self.optional_fulfilled),
            "invalidation_triggered": list(self.invalidation_triggered),
            "expired_reason": self.expired_reason,
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class Scenario:
    scenario_id: str
    scenario_type: ScenarioType
    direction: Direction
    hypothesis: str
    trigger_level: Decimal | None
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    evidence_for: tuple[str, ...]
    evidence_against: tuple[str, ...]
    mandatory_confirmations: tuple[str, ...]
    optional_confirmations: tuple[str, ...]
    invalidation: tuple[str, ...]
    score: Decimal
    score_type: ProbabilityType
    state: ConfirmationState = ConfirmationState.PROPOSED
    confirmation: ScenarioConfirmationState | None = None
    trade_template: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not (ZERO <= self.score <= Decimal("1")):
            raise ValueError("score must be within [0,1]")

    def with_confirmation(self, confirmation: ScenarioConfirmationState) -> "Scenario":
        return Scenario(
            scenario_id=self.scenario_id,
            scenario_type=self.scenario_type,
            direction=self.direction,
            hypothesis=self.hypothesis,
            trigger_level=self.trigger_level,
            entry_zone_low=self.entry_zone_low,
            entry_zone_high=self.entry_zone_high,
            evidence_for=self.evidence_for,
            evidence_against=self.evidence_against,
            mandatory_confirmations=self.mandatory_confirmations,
            optional_confirmations=self.optional_confirmations,
            invalidation=self.invalidation,
            score=self.score,
            score_type=self.score_type,
            state=confirmation.state,
            confirmation=confirmation,
            trade_template=self.trade_template,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "type": self.scenario_type.value,
            "direction": self.direction.value,
            "hypothesis": self.hypothesis,
            "trigger_level": _text(self.trigger_level),
            "entry_zone_low": _text(self.entry_zone_low),
            "entry_zone_high": _text(self.entry_zone_high),
            "evidence_for": list(self.evidence_for),
            "evidence_against": list(self.evidence_against),
            "mandatory_confirmations": list(self.mandatory_confirmations),
            "optional_confirmations": list(self.optional_confirmations),
            "invalidation": list(self.invalidation),
            "score": _text(self.score),
            "score_type": self.score_type.value,
            "state": self.state.value,
            "confirmation": self.confirmation.to_dict() if self.confirmation else None,
            "trade_template": self.trade_template,
        }


@dataclass(frozen=True, slots=True)
class TradePlan:
    trade_id: str
    timestamp: datetime
    symbol: str
    venue: str
    market_type: str
    timeframe: str
    scenario_id: str
    scenario_type: ScenarioType
    direction: Direction
    setup_name: str
    current_market_state: str
    trigger: Decimal
    entry_model: EntryModel
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    exact_entry: Decimal | None
    invalidation_logic: str
    stop_loss: Decimal
    stop_distance: Decimal
    target_1: Decimal
    target_2: Decimal
    target_3: Decimal
    target_logic: str
    expected_reward_risk: Decimal
    minimum_required_reward_risk: Decimal
    confidence: Decimal
    probability_type: ProbabilityType
    supporting_evidence: tuple[str, ...]
    conflicting_evidence: tuple[str, ...]
    conditions_still_missing: tuple[str, ...]
    expiration_condition: str
    maximum_hold_time: str
    management_plan: str
    partial_take_profit_plan: str
    break_even_rule: str
    trailing_rule: str
    cancellation_rule: str
    account_risk: Decimal
    position_size: Decimal
    leverage: Decimal
    liquidation_distance: Decimal | None
    estimated_fees: Decimal
    estimated_slippage: Decimal
    status: TradeStatus
    grade: Grade
    grade_reasons: tuple[str, ...]
    execution_sensitivity: ExecutionSensitivity
    audit_trace: dict[str, Any]
    vetting_mode: VettingMode = VettingMode.NONE

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware")
        for price in (self.trigger, self.stop_loss, self.stop_distance, self.target_1, self.target_2, self.target_3):
            if price is None:
                raise ValueError("trade plan prices must not be None")
        if self.entry_zone_low is not None and self.entry_zone_high is not None and self.entry_zone_high <= self.entry_zone_low:
            raise ValueError("entry zone high must be above entry zone low")
        if self.stop_distance <= ZERO:
            raise ValueError("stop_distance must be positive")
        if self.confidence < ZERO or self.confidence > Decimal("1"):
            raise ValueError("confidence must be within [0,1]")
        if self.position_size < ZERO:
            raise ValueError("position_size cannot be negative")
        if self.leverage < Decimal("1"):
            raise ValueError("leverage must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scenario_type"] = self.scenario_type.value
        data["direction"] = self.direction.value
        data["entry_model"] = self.entry_model.value
        data["probability_type"] = self.probability_type.value
        data["status"] = self.status.value
        data["grade"] = self.grade.value
        data["execution_sensitivity"] = self.execution_sensitivity.value
        data["vetting_mode"] = self.vetting_mode.value
        data["timestamp"] = self.timestamp.isoformat()
        data["supporting_evidence"] = list(self.supporting_evidence)
        data["conflicting_evidence"] = list(self.conflicting_evidence)
        data["conditions_still_missing"] = list(self.conditions_still_missing)
        data["grade_reasons"] = list(self.grade_reasons)
        data["liquidation_distance"] = _text(self.liquidation_distance)
        return data


@dataclass(frozen=True, slots=True)
class RiskDecision:
    status: RiskStatus
    reason_codes: tuple[str, ...]
    details: tuple[str, ...]
    proposed_risk_fraction: Decimal | None
    approved_risk_fraction: Decimal | None
    approved_position_size: Decimal | None
    approved_leverage: Decimal | None
    liquidation_price: Decimal | None
    liquidation_buffer_ok: bool | None

    def approved(self) -> bool:
        return self.status == RiskStatus.APPROVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "details": list(self.details),
            "proposed_risk_fraction": _text(self.proposed_risk_fraction),
            "approved_risk_fraction": _text(self.approved_risk_fraction),
            "approved_position_size": _text(self.approved_position_size),
            "approved_leverage": _text(self.approved_leverage),
            "liquidation_price": _text(self.liquidation_price),
            "liquidation_buffer_ok": self.liquidation_buffer_ok,
        }


@dataclass(frozen=True, slots=True)
class Decision:
    status: DecisionStatus
    reason_codes: tuple[str, ...]
    missing_confirmations: tuple[str, ...]
    next_observation: tuple[str, ...]
    trade_plan: TradePlan | None = None
    risk: RiskDecision | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_codes": list(self.reason_codes),
            "missing_confirmations": list(self.missing_confirmations),
            "next_observation": list(self.next_observation),
            "trade_plan": self.trade_plan.to_dict() if self.trade_plan else None,
            "risk": self.risk.to_dict() if self.risk else None,
        }


@dataclass(frozen=True, slots=True)
class AnalysisOutput:
    schema_version: str
    analysis_id: str
    timestamp: datetime
    market_context: MarketContext
    mode: Mode
    data_quality: DataQualityReport
    market_state: MarketState
    auction_state: AuctionState
    orderflow: OrderflowInterpretation
    scenarios: tuple[Scenario, ...]
    decision: Decision
    report_text: str
    audit: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "analysis_id": self.analysis_id,
            "timestamp": self.timestamp.isoformat(),
            "symbol": self.market_context.symbol,
            "venue": self.market_context.venue,
            "market_type": self.market_context.market_type,
            "timeframe": self.market_context.timeframe,
            "mode": self.mode.value,
            "data_quality": self.data_quality.to_dict(),
            "market_state": self.market_state.to_dict(),
            "auction_state": self.auction_state.to_dict(),
            "orderflow": self.orderflow.to_dict(),
            "scenarios": [item.to_dict() for item in self.scenarios],
            "decision": self.decision.to_dict(),
            "report_text": self.report_text,
            "audit": self.audit,
        }
