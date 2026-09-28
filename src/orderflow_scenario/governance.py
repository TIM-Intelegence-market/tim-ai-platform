"""Governance configuration for the Orderflow Scenario and Trade Decision Manager.

Defines production guards and operational controls for orderflow scenarios:
- Kill switches with configurable block flags and reasons
- Risk configuration limits for trade execution
- Operational mode-specific veto rules
- Main governance enforcement logic

This configuration must be explicit, versioned, and auditable. Any change to
risk limits, mode settings, or kill-switch behavior requires documented
operational governance approval.

The class structure is designed to be deterministic, frozen dataclasses with
proper validation to ensure integrity of governance controls.
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

GOVERNANCE_CONFIG_PATH = Path("config/orderflow_scenario_governance.json")


@dataclass(frozen=True, slots=True)
class KillSwitch:
    """Production kill switch for controlling execution across all modes.

    An enabled kill switch must block ALL execution-capable paths.
    This is a safety mechanism that overrides all other execution settings.
    """

    enabled: bool
    block_live_execution: bool
    block_paper_execution: bool
    block_shadow_execution: bool
    reason: str

    def __post_init__(self) -> None:
        if self.enabled and not self.reason:
            raise ValueError("kill switch must have a documented reason")
        # When enabled, blocking flags take effect
        if self.enabled:
            # Active kill-switch must block every execution-capable path
            if not self.block_live_execution:
                raise ValueError("enabled kill-switch must block live execution (OBSERVE)")
            if not self.block_paper_execution:
                raise ValueError("enabled kill-switch must block paper execution (PAPER)")
            if not self.block_shadow_execution:
                raise ValueError("enabled kill-switch must block shadow execution (SHADOW)")
        else:
            # When disabled, blocking flags must all be False for safety
            if self.block_live_execution or self.block_paper_execution or self.block_shadow_execution:
                raise ValueError("disabled kill-switch must not block any execution")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for audit logging and persistence."""
        return {
            "enabled": self.enabled,
            "block_live_execution": self.block_live_execution,
            "block_paper_execution": self.block_paper_execution,
            "block_shadow_execution": self.block_shadow_execution,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class GovernanceLimits:
    """Risk configuration limits for trade execution controls.

    This class defines the quantitative boundaries for safe trade operations
    across all metrics. All values are deterministic and must be properly
    validated to ensure operational integrity.
    """
    max_daily_loss_fraction: Decimal
    max_weekly_loss_fraction: Decimal
    max_consecutive_losses: int
    max_correlation_ratio: Decimal
    max_account_fraction_per_position: Decimal
    liquidation_buffer_fraction: Decimal
    max_event_risk_entries: int
    data_quality_min_confidence: Decimal
    required_grade_for_trade: str
    max_leverage_above_50x: bool
    max_scenarios: int

    def __post_init__(self) -> None:
        if self.max_daily_loss_fraction <= 0 or self.max_daily_loss_fraction > Decimal("1"):
            raise ValueError("max_daily_loss_fraction must be within (0,1]")
        if self.max_weekly_loss_fraction <= 0 or self.max_weekly_loss_fraction > Decimal("1"):
            raise ValueError("max_weekly_loss_fraction must be within (0,1]")
        if self.max_correlation_ratio <= 0 or self.max_correlation_ratio > Decimal("1"):
            raise ValueError("max_correlation_ratio must be within (0,1]")
        if self.max_account_fraction_per_position <= 0 or self.max_account_fraction_per_position > Decimal("1"):
            raise ValueError("max_account_fraction_per_position must be within (0,1]")
        if self.liquidation_buffer_fraction < 0 or self.liquidation_buffer_fraction > Decimal("1"):
            raise ValueError("liquidation_buffer_fraction must be within [0,1]")

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for audit logging and persistence."""
        return {
            "max_daily_loss_fraction": str(self.max_daily_loss_fraction),
            "max_weekly_loss_fraction": str(self.max_weekly_loss_fraction),
            "max_consecutive_losses": self.max_consecutive_losses,
            "max_correlation_ratio": str(self.max_correlation_ratio),
            "max_account_fraction_per_position": str(self.max_account_fraction_per_position),
            "liquidation_buffer_fraction": str(self.liquidation_buffer_fraction),
            "max_event_risk_entries": self.max_event_risk_entries,
            "data_quality_min_confidence": str(self.data_quality_min_confidence),
            "required_grade_for_trade": self.required_grade_for_trade,
            "max_leverage_above_50x": self.max_leverage_above_50x,
            "max_scenarios": self.max_scenarios,
        }


@dataclass(frozen=True, slots=True)
class OperationalModeGuard:
    """Mode-specific veto rules for different operational modes.

    This class defines execution veto rules for specific modes (OBSERVE, PAPER, SHADOW)
    with documented reasons. Ensures that mode-specific restrictions are explicitly
    defined and auditable.
    """
    mode: Mode
    veto_live: bool
    veto_paper: bool
    veto_shadow: bool
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("mode guard must have a documented reason")

    def violates(self, mode: Mode) -> bool:
        """Check if this mode guard vetoes the given execution mode.

        Args:
            mode: The execution mode to check against this guard's mode.

        Returns:
            True if this guard's mode would veto the specified execution mode.
        """
        if mode == Mode.OBSERVE:
            return self.veto_live or self.veto_paper
        if mode == Mode.PAPER:
            return self.veto_live or self.veto_shadow
        if mode == Mode.SHADOW:
            return self.veto_shadow
        return False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for audit logging and persistence."""
        return {
            "mode": self.mode.value,
            "veto_live": self.veto_live,
            "veto_paper": self.veto_paper,
            "veto_shadow": self.veto_shadow,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class OrderflowScenarioGovernance:
    """Main governance configuration for orderflow scenarios and trade decision management.

    This class enforces production guards and operational controls for the
    Orderflow Scenario and Trade Decision Manager. It provides deterministic
    enforcement logic for kill switches, risk limits, and mode-specific veto rules.

    The governance configuration:
    - Is explicit, versioned, and auditable
    - Enforces that any change requires documented governance approval
    - Provides methods to check execution blocking and mode safety
    - Includes proper error handling for malformed data
    - Can be serialized to a dictionary for persistence
    """
    ruleset_version: str
    kill_switch: KillSwitch
    limits: GovernanceLimits
    mode_guards: tuple[OperationalModeGuard, ...]
    veto_live_execution: bool
    veto_paper_execution: bool
    veto_shadow_execution: bool
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.mode_guards:
            raise ValueError("at least one mode guard is required")
        live_veto = any(guard.veto_live for guard in self.mode_guards)
        paper_veto = any(guard.veto_paper for guard in self.mode_guards)
        shadow_veto = any(guard.veto_shadow for guard in self.mode_guards)
        if live_veto != self.veto_live_execution:
            raise ValueError("veto_live_execution must match any mode guard veto_live")
        if paper_veto != self.veto_paper_execution:
            raise ValueError("veto_paper_execution must match any mode guard veto_paper")
        if shadow_veto != self.veto_shadow_execution:
            raise ValueError("veto_shadow_execution must match any mode guard veto_shadow")

    def blocks_execution(self, mode: Mode) -> bool:
        """Check if execution should be blocked for the given mode.

        Args:
            mode: The execution mode to check (OBSERVE, PAPER, SHADOW).

        Returns:
            True if execution should be blocked, False otherwise.
        """
        if self.kill_switch.enabled and self.kill_switch.block_live_execution and mode == Mode.OBSERVE:
            return True
        if self.kill_switch.enabled and self.kill_switch.block_paper_execution and mode == Mode.PAPER:
            return True
        if self.kill_switch.enabled and self.kill_switch.block_shadow_execution and mode == Mode.SHADOW:
            return True
        for guard in self.mode_guards:
            if guard.violates(mode):
                return True
        return False

    def enforce_mode_safety(self, mode: Mode) -> bool:
        """Check if the given mode passes safety checks.

        Args:
            mode: The execution mode to validate.

        Returns:
            True if the mode passes safety checks (i.e., execution is not blocked),
            False otherwise.
        """
        return not self.blocks_execution(mode)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for audit logging and persistence."""
        return {
            "ruleset_version": self.ruleset_version,
            "kill_switch": self.kill_switch.to_dict(),
            "limits": self.limits.to_dict(),
            "mode_guards": [guard.to_dict() for guard in self.mode_guards],
            "veto_live_execution": self.veto_live_execution,
            "veto_paper_execution": self.veto_paper_execution,
            "veto_shadow_execution": self.veto_shadow_execution,
            "extra": self.extra,
        }


def default_governance_config() -> OrderflowScenarioGovernance:
    """Create the default governance configuration with sensible production values.

    Returns:
        A default OrderflowScenarioGovernance instance configured for production use.
    """
    mode = os.getenv("TIM_OFSC_MODE", "OBSERVE")
    if mode not in {item.value for item in Mode}:
        raise ValueError(f"TIM_OFSC_MODE={mode} is not allowed")

    return OrderflowScenarioGovernance(
        ruleset_version=RULESET_VERSION,
        kill_switch=KillSwitch(
            enabled=True,
            block_live_execution=True,
            block_paper_execution=True,
            block_shadow_execution=True,
            reason="Default kill switch enabled blocks all execution paths",
        ),
        limits=GovernanceLimits(
            max_daily_loss_fraction=Decimal("0.03"),
            max_weekly_loss_fraction=Decimal("0.06"),
            max_consecutive_losses=3,
            max_correlation_ratio=Decimal("0.5"),
            max_account_fraction_per_position=Decimal("0.1"),
            liquidation_buffer_fraction=Decimal("0.05"),
            max_event_risk_entries=1,
            data_quality_min_confidence=Decimal("0.5"),
            required_grade_for_trade="B",
            max_leverage_above_50x=False,
            max_scenarios=3,
        ),
        mode_guards=(
            OperationalModeGuard(
                mode=Mode.OBSERVE,
                veto_live=True,
                veto_paper=True,
                veto_shadow=True,
                reason="OBSERVE mode blocked by active kill-switch",
            ),
            OperationalModeGuard(
                mode=Mode.PAPER,
                veto_live=True,
                veto_paper=True,
                veto_shadow=True,
                reason="PAPER mode blocked by active kill-switch",
            ),
            OperationalModeGuard(
                mode=Mode.SHADOW,
                veto_live=True,
                veto_paper=True,
                veto_shadow=True,
                reason="SHADOW mode blocked by active kill-switch",
            ),
        ),
        veto_live_execution=True,
        veto_paper_execution=True,
        veto_shadow_execution=True,
    )


def load_governance_config(path: Path | None = None) -> OrderflowScenarioGovernance:
    """Load governance config from a JSON file; falls back to default.

    Missing or malformed files are never tolerated when explicitly requested:
    an explicit path must exist and validate.

    Args:
        path: Optional path to the governance config file. If not provided,
            uses the default path.

    Returns:
        An OrderflowScenarioGovernance instance loaded from the file or defaults.

    Raises:
        ValueError: If the file doesn't exist (when explicitly requested) or
            contains malformed data that cannot be validated.
    """
    source = path or GOVERNANCE_CONFIG_PATH
    if not source.exists():
        return default_governance_config()
    raw = json.loads(source.read_text(encoding="utf-8"))
    return governance_config_from_dict(raw)


def governance_config_from_dict(raw: dict[str, Any]) -> OrderflowScenarioGovernance:
    """Create an OrderflowScenarioGovernance instance from a dictionary.

    Args:
        raw: Dictionary containing governance configuration data.

    Returns:
        An OrderflowScenarioGovernance instance.

    Raises:
        ValueError: If the input data is malformed or invalid.
    """
    mode = raw.get("mode", "OBSERVE")
    if mode not in {item.value for item in Mode}:
        raise ValueError(f"mode {mode!r} not allowed")

    kill_switch_data = raw.get("kill_switch", {})
    kill_switch = KillSwitch(
        enabled=kill_switch_data.get("enabled", True),
        block_live_execution=kill_switch_data.get("block_live_execution", False),
        block_paper_execution=kill_switch_data.get("block_paper_execution", False),
        block_shadow_execution=kill_switch_data.get("block_shadow_execution", False),
        reason=kill_switch_data.get("reason", "No reason provided"),
    )

    limits_data = raw.get("limits", {})
    limits = GovernanceLimits(
        max_daily_loss_fraction=Decimal(limits_data.get("max_daily_loss_fraction", "0.03")),
        max_weekly_loss_fraction=Decimal(limits_data.get("max_weekly_loss_fraction", "0.06")),
        max_consecutive_losses=int(limits_data.get("max_consecutive_losses", "3")),
        max_correlation_ratio=Decimal(limits_data.get("max_correlation_ratio", "0.5")),
        max_account_fraction_per_position=Decimal(limits_data.get("max_account_fraction_per_position", "0.1")),
        liquidation_buffer_fraction=Decimal(limits_data.get("liquidation_buffer_fraction", "0.05")),
        max_event_risk_entries=int(limits_data.get("max_event_risk_entries", "1")),
        data_quality_min_confidence=Decimal(limits_data.get("data_quality_min_confidence", "0.5")),
        required_grade_for_trade=limits_data.get("required_grade_for_trade", "B"),
        max_leverage_above_50x=limits_data.get("max_leverage_above_50x", False),
        max_scenarios=int(limits_data.get("max_scenarios", "3")),
    )

    mode_guards = []
    for guard_data in raw.get("mode_guards", []):
        mode_guards.append(
            OperationalModeGuard(
                mode=Mode(guard_data["mode"]),
                veto_live=guard_data.get("veto_live", False),
                veto_paper=guard_data.get("veto_paper", False),
                veto_shadow=guard_data.get("veto_shadow", False),
                reason=guard_data.get("reason", "No reason provided"),
            )
        )

    return OrderflowScenarioGovernance(
        ruleset_version=raw.get("ruleset_version", RULESET_VERSION),
        kill_switch=kill_switch,
        limits=limits,
        mode_guards=tuple(mode_guards),
        veto_live_execution=raw.get("veto_live_execution", False),
        veto_paper_execution=raw.get("veto_paper_execution", False),
        veto_shadow_execution=raw.get("veto_shadow_execution", False),
        extra=raw.get("extra", {}),
    )