"""New Control Center (Cockpit), served under /neu next to the existing pages.

Display only: reads what TIM already writes, never writes data or starts work.
"""

from __future__ import annotations

from src.dashboard.cockpit.lage import build_lage
from src.dashboard.cockpit.page import AREA_BY_KEY, COCKPIT_CSP, lage_body, render_area, render_lage

__all__ = ["AREA_BY_KEY", "COCKPIT_CSP", "build_lage", "lage_body", "render_area", "render_lage"]
