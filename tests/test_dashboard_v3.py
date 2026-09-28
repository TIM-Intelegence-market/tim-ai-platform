from src.dashboard.app import DashboardState, render
from src.dashboard.helpers import _case_status
from src.dashboard.i18n import DE, translate_html
from src.dashboard.layout import NAV_GROUPS


def test_translation_touches_only_whole_text_nodes() -> None:
    page = ("<title>Research Cases · TIM</title><h2>Market Status</h2><p>Market Status is fine</p>"
            "<a title='Market Status' href='/x'>Overview</a><script>const t='Market Status';</script>"
            "<style>.a>b{}</style><td>Research Cases &amp; Missing Evidence</td>")
    out = translate_html(page)
    assert "<title>Research-Fälle · TIM</title>" in out
    assert "<h2>Marktstatus</h2>" in out
    assert "<p>Market Status is fine</p>" in out  # partial match stays untouched
    assert "title='Market Status'" in out  # attributes untouched
    assert "const t='Market Status';" in out  # scripts untouched
    assert ">Überblick</a>" in out
    assert "<td>Research-Fälle und fehlende Belege</td>" in out


def test_catalog_has_no_empty_or_identical_noise() -> None:
    assert all(key and value for key, value in DE.items())


def test_navigation_is_grouped_and_marks_current_page() -> None:
    assert [group for group, _ in NAV_GROUPS] == ["Overview", "Forschung", "Betrieb", "Werkzeuge"]
    routes = [href for _, links in NAV_GROUPS for _, href in links]
    assert len(routes) == len(set(routes)) == 11
    page = render(DashboardState(), "Research Cases")
    assert "<details class='navgroup active'><summary>Forschung</summary>" in page
    assert "<a href='/cases' class='active' aria-current='page'>Research-Fälle</a>" in page
    assert "class='menu-toggle'" in page and "aria-label='Hauptnavigation'" in page


def test_safety_markers_stay_visible_after_redesign() -> None:
    page = render(DashboardState())
    assert "OBSERVE • READ-ONLY" in page
    assert "NO ORDERS OR EXECUTION" in page
    assert "lang='de'" in page


def test_case_lifecycle_badges_do_not_paint_progress_as_error() -> None:
    assert _case_status("OPEN") == _case_status("COLLECTING_EVIDENCE") == _case_status("READY_FOR_REVIEW") == "yellow"
    assert _case_status("CONFIRMED") == "green"
    assert _case_status("CLOSED") == _case_status("REJECTED") == "snapshot"
    assert _case_status("QUARANTINED") == "red"
    assert _case_status("SOMETHING_UNKNOWN") == "red"
    page = render(DashboardState(research_cases=[{"case_id": "case-1", "status": "COLLECTING_EVIDENCE", "evidence": []}]), "Research Cases")
    assert "badge--yellow'>COLLECTING_EVIDENCE" in page


def test_no_page_leaks_unrendered_template_code() -> None:
    pages = ["Overview", "Observations", "Research Cases", "Orderflow", "Signal Research", "Analytics", "Insights",
             "Health Center", "Data Quality Exceptions", "Timeline", "Research"]
    for name in pages:
        page = render(DashboardState(), name)
        assert "{_safe(" not in page and "{_short(" not in page, name


def test_signal_research_shows_each_queue_card_once() -> None:
    page = render(DashboardState(), "Signal Research")
    assert page.count("Aktuelle Research-Warteschlange") == 1
    assert "<b>Pipeline-Version:</b> 3.0.0" in page
