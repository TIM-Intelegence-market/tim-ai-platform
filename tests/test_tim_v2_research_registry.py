from datetime import datetime, timezone
import pytest
from src.tim_v2.research import ExperimentPlan, Hypothesis, ResearchRegistry
from src.tim_v2.research.models import ResearchStatus

NOW=datetime(2026,7,28,tzinfo=timezone.utc)

def plan(registry):
    hypothesis=Hypothesis("hypothesis_one","Bounded hypothesis.",("evidence_one",),"owner",.7,ResearchStatus.DRAFT,NOW,NOW)
    registry.add_hypothesis(hypothesis)
    value=ExperimentPlan("plan_one","1.0.0",hypothesis.hypothesis_id,"btc_spot_ticks@1.0.0","metric","split","embargo","code","a"*64,{"window":"20"})
    registry.add_plan(value); return value

def test_plan_manifest_and_replay_are_deterministic():
    registry=ResearchRegistry(); value=plan(registry)
    assert registry.replay(value.plan_id).manifest_sha256==value.manifest_sha256()
    assert registry.replay(value.plan_id).state=="PLANNED_REPLAY_ONLY"

def test_plan_requires_registered_hypothesis_and_leakage_control():
    registry=ResearchRegistry()
    with pytest.raises(ValueError,match="EXPERIMENT_PLAN_INVALID"):
        registry.add_plan(ExperimentPlan("plan_two","1","missing","data","metric","split","","code","a"*64))

def test_immutable_hypothesis_and_unknown_replay_abstain():
    registry=ResearchRegistry(); value=plan(registry)
    with pytest.raises(ValueError,match="IMMUTABLE_RECORD_CONFLICT"):
        registry.add_hypothesis(Hypothesis("hypothesis_one","Changed",("evidence_one",),"owner",.7,ResearchStatus.DRAFT,NOW,NOW))
    assert registry.replay("missing").state=="ABSTAIN"
