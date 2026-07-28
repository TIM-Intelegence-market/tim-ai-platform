from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ResearchConfig:
    cache_path: Path = field(default_factory=lambda: Path(os.getenv("TIM_RESEARCH_CACHE", "data/research/module_a_cache.jsonl")))
    report_root: Path = field(default_factory=lambda: Path(os.getenv("TIM_RESEARCH_REPORT_ROOT", "data/research/module_b_reports")))
    external_search_enabled: bool = field(default_factory=lambda: os.getenv("TIM_RESEARCH_EXTERNAL_SEARCH", "false").lower()=="true")
    module_b_enabled: bool = field(default_factory=lambda: os.getenv("TIM_RESEARCH_MODULE_B", "false").lower()=="true")
    mode: str = "OBSERVE"
    provenance: str = "PUBLIC_MARKET_DATA_DETERMINISTIC"


research_config=ResearchConfig()
