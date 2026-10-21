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


def _live_data() -> dict:
    data = DashboardState(recent_candles=[{"close": 80_000 + index} for index in range(20)]).snapshot()
    data["operational_health"] = {"status": "GREEN", "data_age_seconds": 1}
    data["research_quality"] = {}
    return data


def test_setup_path_uses_rolling_liveness_when_quality_report_missing() -> None:
    data = _live_data()
    data["operations"] = {"datasets": [
        {"label": "Backfill Candidate", "coverage": "100.000%", "status": "CANDIDATE PASS", "source": "artifacts/x.json"},
        {"label": "Rolling Liveness", "coverage": "100.000%", "status": "PASS", "source": "data/operational/rolling_liveness.json"},
    ]}
    page = _setup_path_page(data)
    assert "Frische Daten, mindestens 20 Candles" in page
    assert "Rolling Liveness 24h (100.000%)" in page


def test_setup_path_blocks_when_rolling_liveness_fails() -> None:
    data = _live_data()
    data["operations"] = {"datasets": [{"coverage": "90.000%", "status": "FAIL", "source": "data/operational/rolling_liveness.json"}]}
    page = _setup_path_page(data)
    assert "bestätigte Datenqualität fehlt" in page


def test_setup_path_stays_blocked_without_any_quality_evidence() -> None:
    page = _setup_path_page(_live_data())
    assert "bestätigte Datenqualität fehlt" in page
    assert "kein Qualitätsnachweis vorhanden" in page


def test_setup_path_report_takes_precedence_over_rolling_liveness() -> None:
    data = _live_data()
    data["research_quality"] = {"validation_status": "FAIL"}
    data["operations"] = {"datasets": [{"coverage": "100.000%", "status": "PASS", "source": "data/operational/rolling_liveness.json"}]}
    assert "bestätigte Datenqualität fehlt" in _setup_path_page(data)


def test_orderflow_pending_shows_due_time() -> None:
    from src.dashboard.views import _pending_label

    assert _pending_label("2026-10-20T22:55:00+00:00") == "PENDING · ab 23:25 UTC"
    assert _pending_label("kaputt") == "PENDING"


def test_timeline_falls_back_to_process_start_without_validator_state() -> None:
    state = DashboardState()
    events = state.snapshot()["timeline"]
    assert events and events[0]["event"] == "RUNTIME_START"
    assert events[0]["timestamp"] == state.runtime_started_at
