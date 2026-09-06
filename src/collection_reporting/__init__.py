from .reporter import CollectionReportBuilder, CollectionReportError
from .collector import CollectionPreflightError, collect_read_only_facts
from .errors import ErrorClass, ErrorPolicy, classify_error
from .gaps import GAP_CATEGORIES, MissingRange, load_gap_classification, missing_ranges

__all__ = [
    "CollectionPreflightError",
    "CollectionReportBuilder",
    "CollectionReportError",
    "collect_read_only_facts",
    "ErrorClass",
    "ErrorPolicy",
    "classify_error",
    "MissingRange",
    "GAP_CATEGORIES",
    "load_gap_classification",
    "missing_ranges",
]
