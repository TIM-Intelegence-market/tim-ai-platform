"""Feature contracts only; no calculation or execution."""
from .models import FeatureDefinition, FeatureValidity
from .registry import FeatureRegistry
__all__ = ["FeatureDefinition", "FeatureRegistry", "FeatureValidity"]
