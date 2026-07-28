from .models import SimulationRun
class SimulationRegistry:
 def __init__(self):self._runs={}
 def register(self,value):
  issues=value.issues()
  if issues:raise ValueError(";".join(issues))
  old=self._runs.get(value.run_id)
  if old is None:self._runs[value.run_id]=value
  elif old!=value:raise ValueError(f"IMMUTABLE_SIMULATION_CONFLICT:{value.run_id}")
  return value
