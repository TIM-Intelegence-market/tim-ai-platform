"""New Control Center (Cockpit), served under /neu next to the existing pages.

Display only: reads what TIM already writes, never writes data or starts work.
"""

from __future__ import annotations

from src.dashboard.cockpit.areas import build_betrieb, build_forschung, build_system
from src.dashboard.cockpit.lage import build_lage
from src.dashboard.cockpit.mac import build_mac
from src.dashboard.cockpit.markt import build_markt
from src.dashboard.cockpit.page import (
    AREA_BY_KEY, COCKPIT_CSP, lage_body, mac_body, markt_body, render_area, render_lage, render_mac, render_markt,
    render_sections, sections_body,
)

# Areas with their own page: (model builder, refreshable body, full page).
BUILT = {
    "lage": (build_lage, lage_body, render_lage),
    "markt": (build_markt, markt_body, render_markt),
    "mac": (build_mac, mac_body, render_mac),
    "forschung": (build_forschung, sections_body, render_sections),
    "betrieb": (build_betrieb, sections_body, render_sections),
    "system": (build_system, sections_body, render_sections),
}

__all__ = ["AREA_BY_KEY", "BUILT", "COCKPIT_CSP", "build_betrieb", "build_forschung", "build_system", "build_lage", "build_mac", "build_markt", "lage_body", "mac_body", "markt_body",
           "render_area", "render_lage", "render_mac", "render_markt", "render_sections", "sections_body"]
