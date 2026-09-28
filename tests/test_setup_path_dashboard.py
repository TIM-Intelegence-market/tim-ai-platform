from src.dashboard.app import DashboardState, _setup_path_page, render


def test_setup_path_is_read_only_and_blocks_without_fresh_history() -> None:
    page = render(DashboardState(), page="Setup Path")
    assert "Setup-Pfad" in page  # German label (src/dashboard/i18n.py)
    assert "Analyse-Gate" in page
    assert "BLOCKED" in page
    assert "Live-Synchronisierung aktiv" in page
    assert "Neue Daten erkannt" in page
    assert "keine Trading-" in page


def test_setup_path_renders_chart_for_candle_history() -> None:
    candles = [{"close": 80_000 + index} for index in range(20)]
    page = render(DashboardState(recent_candles=candles), page="Setup Path")
    assert "Beobachtete Schlusskurse" in page
    assert "setup-chart__line" in page


def test_setup_path_blocks_when_quality_fails_even_with_live_candles() -> None:
    data = DashboardState(recent_candles=[{"close": 80_000 + index} for index in range(20)]).snapshot()
    data["operational_health"] = {"status": "GREEN", "data_age_seconds": 1}
    data["research_quality"] = {"validation_status": "FAIL"}
    page = _setup_path_page(data)
    assert "BLOCKED" in page
    assert "bestätigte Datenqualität fehlt" in page
