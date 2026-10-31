"""Control Center frame (new Control Center 31.10.2026, replaces the P3 light layer).

One dark frame for every page: four screens in a side bar (on the phone a bar at
the bottom), the header with price, system light and "Papier". The frame's CSS
only touches pages with body.ncc, so the public English view keeps its look.
"""
from __future__ import annotations

import re
from urllib.request import urlopen

import pytest

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.cockpit.page import STYLE
from src.dashboard.layout import EXTRA_CSS
from src.dashboard.shell import SHELL_CSS


@pytest.fixture()
def port():
    srv = DashboardServer(DashboardState(), port=0)
    srv.start()
    yield srv.server.server_address[1]
    srv.stop()


def test_frame_css_only_touches_frame_pages() -> None:
    css = re.sub(r"/\*.*?\*/", "", SHELL_CSS, flags=re.S).replace("@media (max-width:700px){", "")
    for rule in css.split("}"):
        selector = rule.split("{", 1)[0].strip()
        if selector:
            assert all("ncc" in part for part in re.split(r",(?![^(]*\))", selector)), selector
    assert "Light look for every Control Center page" not in EXTRA_CSS  # the light layer is gone: one dark look
    assert SHELL_CSS in EXTRA_CSS and SHELL_CSS in STYLE  # same frame on detail pages and /neu areas
    phone = SHELL_CSS[SHELL_CSS.index("@media (max-width:700px){"):]
    assert ".ncc-side{top:auto" in phone  # the side bar becomes the bar at the bottom


@pytest.mark.parametrize("path", ["/", "/trades", "/forschung", "/system", "/journal", "/runtime", "/neu/markt"])
def test_every_page_has_the_four_screens_and_the_header(port: int, path: str) -> None:
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=20) as response:
        page = response.read().decode()
    nav = page.split("class='ncc-nav' aria-label='Hauptnavigation'>", 1)[1].split("</nav>", 1)[0]
    assert nav.count("<a ") == 4
    assert "Papier · kein Echtgeld" in page and "class='ncc-price'" in page
    assert "name='color-scheme' content='dark'" in page
