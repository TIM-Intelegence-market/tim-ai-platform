"""Dataset catalog contracts; deliberately no data ingestion or storage."""

from .models import DatasetVersion, QualityMetrics, TimeRange, ValidationState
from .registry import DatasetRegistry, RegistrationResult

__all__ = [
    "DatasetRegistry",
    "DatasetVersion",
    "QualityMetrics",
    "RegistrationResult",
    "TimeRange",
    "ValidationState",
]
