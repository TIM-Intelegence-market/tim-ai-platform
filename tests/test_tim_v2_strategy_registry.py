import pytest
from src.tim_v2.strategy.models import StrategyCandidate
from src.tim_v2.strategy.registry import StrategyRegistry
def value(state="EVALUATION_REQUIRED"): return StrategyCandidate("candidate","1.0.0","policy",("spread@1",),("claim:one",),"bounded",state)
def test_candidate_is_immutable_and_non_executable():
    registry=StrategyRegistry(); assert registry.register(value())==value()
def test_execution_state_is_rejected():
    with pytest.raises(ValueError,match="STRATEGY_EXECUTION_FORBIDDEN"): StrategyRegistry().register(value("EXECUTE"))
