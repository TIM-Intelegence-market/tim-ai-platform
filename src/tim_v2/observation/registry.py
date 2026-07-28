from .models import Observation
class ObservationRegistry:
 def __init__(self):self._items={}
 def register(self,value):
  issues=value.issues()
  if issues:raise ValueError(";".join(issues))
  old=self._items.get(value.observation_id)
  if old is None:self._items[value.observation_id]=value
  elif old!=value:raise ValueError(f"IMMUTABLE_OBSERVATION_CONFLICT:{value.observation_id}")
  return value
