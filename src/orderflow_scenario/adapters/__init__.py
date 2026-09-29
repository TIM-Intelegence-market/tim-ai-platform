"""Input adapters for the Orderflow Scenario and Trade Decision Manager.

The core system never depends on a specific UI provider. Adapters translate
provider-specific inputs (e.g. an MMT.GG screenshot or an MMT structured
export) into normalized `AdapterInput`, and they always mark which values are
estimated, which are certain, and which are missing. A screenshot is never
treated as fully structured market data.
"""

from .base import AdapterInput, AdapterResult, ListPathEntry
from .generic import GenericOrderflowAdapter
from .mmt_structured import MMTStructuredDataAdapter
from .mmt_screenshot import MMTScreenshotAdapter
from .openmarket import OpenMarketAdapter, OpenMarketRequest

__all__ = [
    "AdapterInput",
    "AdapterResult",
    "ListPathEntry",
    "GenericOrderflowAdapter",
    "MMTStructuredDataAdapter",
    "MMTScreenshotAdapter",
    "OpenMarketAdapter",
    "OpenMarketRequest",
]