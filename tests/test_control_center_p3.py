"""Control Center P3 (Beirat 29.10.2026): phone bar and one light look for every page."""
from __future__ import annotations

import re
from urllib.request import urlopen

import pytest

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.cockpit.page import STYLE
from src.dashboard.layout import EXTRA_CSS


@pytest.fixture()
def port():
    srv = DashboardServer(DashboardState(), port=0)
    srv.start()
    yield srv.server.server_address[1]
    srv.stop()


def test_light_layer_and_phone_bar_only_touch_control_center_pages() -> None:
    light = re.sub(r"/\*.*?\*/", "", EXTRA_CSS[EXTRA_CSS.index("/* Light look for every Control Center page"):], flags=re.S)
    # every rule of the layer is scoped to .cc, so the public English view (no .cc) keeps its look
    for rule in light.replace("@media (prefers-color-scheme:light){", "").replace("@media (max-width:700px){", "").split("}"):
        selector = rule.split("{", 1)[0].strip()
        if selector:
            assert all(".cc" in part for part in re.split(r",(?![^(]*\))", selector)), selector
    assert "position:fixed;left:0;right:0;bottom:0" in light
    assert "position:fixed;left:0;right:0;bottom:0" in STYLE  # same bar on the /neu areas


@pytest.mark.parametrize("path", ["/journal", "/runtime", "/neu"])
def test_pages_still_have_exactly_five_area_links(port: int, path: str) -> None:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
        page = response.read().decode()
    nav = page.split("class='nav' aria-label=", 1)[1].split("</nav>", 1)[0]
    assert nav.count("<a ") == 5
    assert "name='color-scheme' content='light dark'" in page or path == "/neu"
