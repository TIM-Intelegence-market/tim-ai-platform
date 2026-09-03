#!/usr/bin/env python3
"""Test governance validation rules for Orderflow Scenario and Trade Decision Manager."""

from src.orderflow_scenario.governance import (
    OrderflowScenarioGovernance,
    KillSwitch,
    GovernanceLimits,
    OperationalModeGuard,
    default_governance_config,
)
from src.orderflow_scenario.domain import Mode
from src.orderflow_scenario.version import RULESET_VERSION
from decimal import Decimal

def test_default_governance():
    """Test that default governance configuration follows all rules."""
    gov = default_governance_config()
    
    # Rule 1: Enabled kill-switch must block all execution paths
    assert gov.kill_switch.enabled, "Kill-switch should be enabled"
    assert gov.kill_switch.block_live_execution, "Kill-switch should block live execution"
    assert gov.kill_switch.block_paper_execution, "Kill-switch should block paper execution"
    assert gov.kill_switch.block_shadow_execution, "Kill-switch should block shadow execution"
    
    # Rule 2: kill_switch.enabled must match mode guard veto flags
    live_veto = any(guard.veto_live for guard in gov.mode_guards)
    paper_veto = any(guard.veto_paper for guard in gov.mode_guards)
    shadow_veto = any(guard.veto_shadow for guard in gov.mode_guards)
    
    assert gov.veto_live_execution == live_veto, "veto_live_execution must match any mode guard veto_live"
    assert gov.veto_paper_execution == paper_veto, "veto_paper_execution must match any mode guard veto_paper"
    assert gov.veto_shadow_execution == shadow_veto, "veto_shadow_execution must match any mode guard veto_shadow"
    
    # Rule 3: Disabled kill-switch must not have any block flags
    try:
        invalid_gov = OrderflowScenarioGovernance(
            ruleset_version=RULESET_VERSION,
            kill_switch=KillSwitch(
                enabled=False,
                block_live_execution=True,
                block_paper_execution=False,
                block_shadow_execution=False,
                reason="Invalid test - disabled with block flag",
            ),
            limits=gov.limits,
            mode_guards=gov.mode_guards,
            veto_live_execution=gov.veto_live_execution,
            veto_paper_execution=gov.veto_paper_execution,
            veto_shadow_execution=gov.veto_shadow_execution,
        )
        assert False, "Invalid governance should have been rejected"
    except ValueError as e:
        assert "disabled kill-switch must not block any execution" in str(e)
    
    print("✅ Governance validation tests passed")
    return True

if __name__ == "__main__":
    test_default_governance()
