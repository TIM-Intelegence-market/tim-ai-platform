"""One navigation, five areas (Beirat 29.10.2026).

These tests keep the Control Center from growing back into a 28-entry menu:
the top level stays at five German areas, every listed page is served, the
V2 campaign pages live only on /archiv, and the start page is "Heute".
"""
from __future__ import annotations

import re
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from src.dashboard.app import DashboardServer, DashboardState
from src.dashboard.navigation import AREAS, ARCHIVE, links, locate
from src.dashboard.public_en import NAV as PUBLIC_NAV

# Words of the old English menu; none of them may come back as a label.
# ("Research", "Signal", "Setup", "Audit", "Trader" stay: they are the established TIM terms.)
ENGLISH = {"overview", "runtime", "data", "quality", "incidents", "gaps", "health", "center", "exceptions", "timeline",
           "observations", "cases", "analytics", "insights", "independent", "qualification", "prep", "my", "day",
           "path", "readiness", "security", "evidence", "needs", "attention", "today", "settings", "journey"}


def test_top_level_has_exactly_five_german_areas() -> None:
    assert len(AREAS) == 5, "Neue Seiten gehören als Unterpunkt in einen der fünf Bereiche, nicht als sechster Bereich."
    labels = [area["label"] for area in AREAS] + [label for area in AREAS for label, _ in area["pages"]]
    for label in labels:
        words = {w.lower() for w in re.findall(r"[A-Za-zÄÖÜäöüß]+", label)}
        assert not words & ENGLISH, f"englisches Wort im Menü: {label}"


def test_every_page_belongs_to_one_area_and_archive_stays_out() -> None:
    hrefs = [href for area in AREAS for _, href in area["pages"]]
    assert len(hrefs) == len(set(hrefs))
    archive = {href for _, href, _ in ARCHIVE}
    assert archive.isdisjoint(hrefs)
    for href in archive:
        assert locate(href) == ("system", "/archiv")
    assert locate("/neu") == ("heute", "/") and locate("/journal/struct") == ("journal", "/journal")


def test_links_open_only_the_active_area() -> None:
    nav = links("/runtime")
    assert [a["label"] for a in nav] == ["Heute", "Chart", "Journal", "Forschung", "System"]
    assert [bool(a["pages"]) for a in nav] == [False, False, False, False, True]
    assert sum(1 for a in nav for s in a["pages"] if s["current"]) == 1  # type: ignore[union-attr]


@pytest.fixture()
def server():
    srv = DashboardServer(DashboardState(), port=0)
    srv.start()
    yield srv.server.server_address[1]
    srv.stop()


def _get(port: int, path: str) -> tuple[int, str]:
    try:
        with urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as response:
            return response.status, response.read().decode()
    except HTTPError as error:
        return error.code, ""


def test_every_navigation_target_is_served(server: int) -> None:
    targets = {href for area in AREAS for _, href in area["pages"]} | {href for _, href, _ in ARCHIVE}
    for href in sorted(targets):
        status, _ = _get(server, href)
        allowed = (200, 404) if href == "/graphify" else (200,)  # 404 = graph not built yet on this machine
        assert status in allowed, f"{href} -> {status}"


def test_start_page_is_heute_without_old_menu(server: int) -> None:
    status, page = _get(server, "/")
    assert status == 200
    assert "<title>Lage · TIM</title>" in page
    assert "Bisheriges Dashboard" not in page and "Needs attention" not in page
    nav = page.split("aria-label='Bereiche'>", 1)[1].split("</nav>", 1)[0]
    assert nav.count("<a ") == 5
    assert "aria-label='Seiten in diesem Bereich'" in page and "href='/neu/markt'" in page


def test_archive_page_lists_the_campaign_pages(server: int) -> None:
    status, page = _get(server, "/archiv")
    assert status == 200 and "Archiv V2" in page
    for _, href, _ in ARCHIVE:
        assert f"href='{href}'" in page


def test_public_read_only_view_keeps_its_own_menu() -> None:
    assert PUBLIC_NAV == (("/chart", "Chart"), ("/journal", "Paper journal"))
