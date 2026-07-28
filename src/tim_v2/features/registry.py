from .models import FeatureDefinition
class FeatureRegistry:
    def __init__(self)->None:self._features:dict[str,FeatureDefinition]={}
    def register(self,value:FeatureDefinition)->FeatureDefinition:
        key=f"{value.feature_id}@{value.version}"; issues=list(value.issues())
        issues.extend(f"FEATURE_DEPENDENCY_NOT_FOUND:{item}" for item in value.dependencies if item not in self._features)
        if issues:raise ValueError(";".join(issues))
        old=self._features.get(key)
        if old is None:self._features[key]=value
        elif old!=value:raise ValueError(f"IMMUTABLE_FEATURE_CONFLICT:{key}")
        return value
