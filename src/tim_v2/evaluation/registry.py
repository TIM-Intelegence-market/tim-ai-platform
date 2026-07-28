from .models import EvaluationPlan
class EvaluationRegistry:
 def __init__(self):self._plans={}
 def register(self,value):
  issues=value.issues()
  if issues:raise ValueError(";".join(issues))
  old=self._plans.get(value.evaluation_id)
  if old is None:self._plans[value.evaluation_id]=value
  elif old!=value:raise ValueError(f"IMMUTABLE_EVALUATION_CONFLICT:{value.evaluation_id}")
  return "RECOMMENDATION_ONLY"
