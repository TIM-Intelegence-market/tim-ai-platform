from .models import StrategyCandidate
class StrategyRegistry:
    def __init__(self): self._items={}
    def register(self,value):
        issues=value.issues()
        if issues: raise ValueError(";".join(issues))
        key=f"{value.strategy_id}@{value.version}"; old=self._items.get(key)
        if old is None: self._items[key]=value
        elif old!=value: raise ValueError(f"IMMUTABLE_STRATEGY_CONFLICT:{key}")
        return value
