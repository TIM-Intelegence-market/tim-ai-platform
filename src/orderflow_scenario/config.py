"""Configuration for the Orderflow Scenario and Trade Decision Manager.

All configuration is explicit, versioned, and loaded only from local files or
environment variables. There is deliberately no way to configure live order
execution: `mode` is restricted to OBSERVE / RESEARCH / SIMULATE / PAPER /
SHADOW and the pipeline refuses any other value.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

from .domain import Mode, VettingMode
from .version import RULESET_VERSION

DEFAULT_CONFIG_PATH = Path("config/orderflow_scenario.json")
ALLOWED_MODES = {Mode.OBSERVE, Mode.RESEARCH, Mode.SIMULATE, Mode.PAPER, Mode.SHADOW}

# Feste Obergrenze für den Hebel (Uzi, 2026-10-20): Spot (1x) und Hebel bis
# höchstens 10x. Kein Tier und keine Konfigurationsdatei kann darüber gehen.
MAX_LEVERAGE = Decimal("10")
SPOT_LEVERAGE = Decimal("1")


def _d(value: str | int | float | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True, slots=True)
class RiskTier:
    name: str
    account_risk_fraction: Decimal
    max_leverage: Decimal
    min_reward_risk: Decimal

    def __post_init__(self) -> None:
        if not (Decimal("0") < self.account_risk_fraction <= Decimal("0.02")):
            raise ValueError("account_risk_fraction must be within (0, 2%]")
        if self.max_leverage < SPOT_LEVERAGE:
            raise ValueError("max_leverage must be >= 1")
        if self.max_leverage > MAX_LEVERAGE:
            raise ValueError(f"max_leverage must be <= {MAX_LEVERAGE} (hard cap)")
        if self.min_reward_risk < Decimal("0.5"):
            raise ValueError("min_reward_risk must be >= 0.5")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "account_risk_fraction": str(self.account_risk_fraction),
            "max_leverage": str(self.max_leverage),
            "min_reward_risk": str(self.min_reward_risk),
        }


@dataclass(frozen=True, slots=True)
class RiskLimits:
    daily_loss_fraction: Decimal
    weekly_loss_fraction: Decimal
    max_consecutive_losses: int
    max_correlation_ratio: Decimal
    max_account_fraction_per_position: Decimal
    liquidation_buffer_fraction: Decimal
    max_event_risk_entries: int
    data_quality_min_confidence: Decimal
    required_grade_for_trade: str

    def __post_init__(self) -> None:
        for name in ("daily_loss_fraction", "weekly_loss_fraction", "max_correlation_ratio", "max_account_fraction_per_position", "liquidation_buffer_fraction", "data_quality_min_confidence"):
            value = getattr(self, name)
            if not (Decimal("0") <= value <= Decimal("1")):
                raise ValueError(f"{name} must be within [0,1]")
        if self.max_consecutive_losses < 0 or self.max_event_risk_entries < 0:
            raise ValueError("count limits cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_loss_fraction": str(self.daily_loss_fraction),
            "weekly_loss_fraction": str(self.weekly_loss_fraction),
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_correlation_ratio": str(self.max_correlation_ratio),
            "max_account_fraction_per_position": str(self.max_account_fraction_per_position),
            "liquidation_buffer_fraction": str(self.liquidation_buffer_fraction),
            "data_quality_min_confidence": str(self.data_quality_min_confidence),
            "required_grade_for_trade": self.required_grade_for_trade,
        }


@dataclass(frozen=True, slots=True)
class FeeModel:
    taker_bps: Decimal
    maker_bps: Decimal
    slippage_bps: Decimal

    def __post_init__(self) -> None:
        if self.taker_bps < 0 or self.maker_bps < 0 or self.slippage_bps < 0:
            raise ValueError("fees and slippage cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return {"taker_bps": str(self.taker_bps), "maker_bps": str(self.maker_bps), "slippage_bps": str(self.slippage_bps)}


@dataclass(frozen=True, slots=True)
class OrderflowScenarioConfig:
    ruleset_version: str
    mode: Mode
    vetting_mode: VettingMode
    default_risk_tier: str
    risk_tiers: tuple[RiskTier, ...]
    risk_limits: RiskLimits
    fee_model: FeeModel
    max_scenarios: int
    default_timeframe: str
    kill_switch_enabled: bool = True
    allow_leverage_above_50x: bool = False
    calibration_required: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.mode not in ALLOWED_MODES:
            raise ValueError(f"mode {self.mode!r} is not an allowed operational mode")
        if self.vetting_mode == VettingMode.NONE and self.mode in {Mode.PAPER, Mode.SHADOW}:
            raise ValueError("vetting mode must be set for PAPER/SHADOW mode")
        if self.max_scenarios < 2 or self.max_scenarios > 5:
            raise ValueError("max_scenarios must be within [2,5]")
        if not any(tier.name == self.default_risk_tier for tier in self.risk_tiers):
            raise ValueError(f"default risk tier {self.default_risk_tier!r} not defined")

    def tier(self, name: str | None = None) -> RiskTier:
        target = name or self.default_risk_tier
        for tier in self.risk_tiers:
            if tier.name == target:
                return tier
        raise ValueError(f"risk tier {target!r} not defined")

    def to_dict(self) -> dict[str, Any]:
        return {
            "ruleset_version": self.ruleset_version,
            "mode": self.mode.value,
            "vetting_mode": self.vetting_mode.value,
            "default_risk_tier": self.default_risk_tier,
            "risk_tiers": [tier.to_dict() for tier in self.risk_tiers],
            "risk_limits": self.risk_limits.to_dict(),
            "fee_model": self.fee_model.to_dict(),
            "max_scenarios": self.max_scenarios,
            "default_timeframe": self.default_timeframe,
            "kill_switch_enabled": self.kill_switch_enabled,
            "allow_leverage_above_50x": self.allow_leverage_above_50x,
            "calibration_required": self.calibration_required,
            "extra": self.extra,
        }


def default_config() -> OrderflowScenarioConfig:
    mode = os.getenv("TIM_OFSC_MODE", "OBSERVE").upper()
    if mode not in {item.value for item in Mode}:
        raise ValueError(f"TIM_OFSC_MODE={mode} is not allowed; allowed: {[item.value for item in ALLOWED_MODES]}")
    return OrderflowScenarioConfig(
        ruleset_version=RULESET_VERSION,
        mode=Mode(mode),
        vetting_mode=VettingMode.NONE if mode in {"OBSERVE", "RESEARCH", "SIMULATE"} else VettingMode(mode),
        default_risk_tier="STANDARD",
        risk_tiers=(
            RiskTier("CONSERVATIVE", Decimal("0.0025"), Decimal("5"), Decimal("1.5")),
            RiskTier("STANDARD", Decimal("0.005"), MAX_LEVERAGE, Decimal("1.5")),
            RiskTier("AGGRESSIVE", Decimal("0.01"), MAX_LEVERAGE, Decimal("2.0")),
        ),
        risk_limits=RiskLimits(
            daily_loss_fraction=Decimal("0.03"),
            weekly_loss_fraction=Decimal("0.06"),
            max_consecutive_losses=3,
            max_correlation_ratio=Decimal("0.5"),
            max_account_fraction_per_position=Decimal("0.1"),
            liquidation_buffer_fraction=Decimal("0.05"),
            max_event_risk_entries=1,
            data_quality_min_confidence=Decimal("0.5"),
            required_grade_for_trade="B",
        ),
        fee_model=FeeModel(Decimal("6"), Decimal("2"), Decimal("2")),
        max_scenarios=3,
        default_timeframe="4H",
        kill_switch_enabled=True,
        allow_leverage_above_50x=False,
        calibration_required=True,
    )


def load_config(path: Path | None = None) -> OrderflowScenarioConfig:
    """Load config from a JSON file; falls back to the default configuration.

    Missing or malformed files are never tolerated when explicitly requested:
    an explicit path must exist and validate.
    """
    source = path or DEFAULT_CONFIG_PATH
    if not source.exists():
        return default_config()
    raw = json.loads(source.read_text(encoding="utf-8"))
    return config_from_dict(raw)


def config_from_dict(raw: dict[str, Any]) -> OrderflowScenarioConfig:
    mode = raw.get("mode", "OBSERVE")
    if mode not in {item.value for item in Mode}:
        raise ValueError(f"mode {mode!r} not allowed")
    return OrderflowScenarioConfig(
        ruleset_version=raw.get("ruleset_version", RULESET_VERSION),
        mode=Mode(mode),
        vetting_mode=VettingMode(raw.get("vetting_mode", "NONE")),
        default_risk_tier=raw.get("default_risk_tier", "STANDARD"),
        risk_tiers=tuple(
            RiskTier(
                name=item["name"],
                account_risk_fraction=_d(item["account_risk_fraction"]),
                max_leverage=_d(item["max_leverage"]),
                min_reward_risk=_d(item["min_reward_risk"]),
            )
            for item in raw.get("risk_tiers", [t.to_dict() for t in default_config().risk_tiers])
        ),
        risk_limits=_risk_limits_from_dict(raw.get("risk_limits", default_config().risk_limits.to_dict())),
        fee_model=_fee_model_from_dict(raw.get("fee_model", default_config().fee_model.to_dict())),
        max_scenarios=raw.get("max_scenarios", 3),
        default_timeframe=raw.get("default_timeframe", "4H"),
        kill_switch_enabled=raw.get("kill_switch_enabled", True),
        allow_leverage_above_50x=raw.get("allow_leverage_above_50x", False),
        calibration_required=raw.get("calibration_required", True),
        extra=raw.get("extra", {}),
    )


def _risk_limits_from_dict(raw: dict[str, Any]) -> RiskLimits:
    defaults = default_config().risk_limits.to_dict()
    return RiskLimits(
        daily_loss_fraction=_d(raw.get("daily_loss_fraction", defaults["daily_loss_fraction"])),
        weekly_loss_fraction=_d(raw.get("weekly_loss_fraction", defaults["weekly_loss_fraction"])),
        max_consecutive_losses=int(raw.get("max_consecutive_losses", defaults["max_consecutive_losses"])),
        max_correlation_ratio=_d(raw.get("max_correlation_ratio", defaults["max_correlation_ratio"])),
        max_account_fraction_per_position=_d(raw.get("max_account_fraction_per_position", defaults["max_account_fraction_per_position"])),
        liquidation_buffer_fraction=_d(raw.get("liquidation_buffer_fraction", defaults["liquidation_buffer_fraction"])),
        max_event_risk_entries=int(raw.get("max_event_risk_entries", defaults["max_event_risk_entries"])),
        data_quality_min_confidence=_d(raw.get("data_quality_min_confidence", defaults["data_quality_min_confidence"])),
        required_grade_for_trade=raw.get("required_grade_for_trade", defaults["required_grade_for_trade"]),
    )


def _fee_model_from_dict(raw: dict[str, Any]) -> FeeModel:
    return FeeModel(_d(raw["taker_bps"]), _d(raw["maker_bps"]), _d(raw["slippage_bps"]))
