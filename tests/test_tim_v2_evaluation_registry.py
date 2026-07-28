import pytest
from src.tim_v2.evaluation.models import EvaluationPlan
from src.tim_v2.evaluation.registry import EvaluationRegistry
def plan(leakage=True):return EvaluationPlan("eval","strategy@1","hypothesis","dataset","split","event",("metric",),"benchmark","seed","cost","robust",("limit",),"manual",("walk_forward","monte_carlo"),leakage,True,True,True)
def test_evaluation_is_recommendation_only():assert EvaluationRegistry().register(plan())=="RECOMMENDATION_ONLY"
def test_leakage_blocks_evaluation():
 with pytest.raises(ValueError,match="EVALUATION_LEAKAGE_BLOCK"):EvaluationRegistry().register(plan(False))
