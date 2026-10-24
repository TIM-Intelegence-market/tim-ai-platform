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


GOVERNANCE_ONLY_FAIL = {
    "validation_status": "FAIL",
    "checks": {"schema_valid": True, "timestamp_integrity": True, "forward_only": True, "deterministic": False,
               "observe_only": True, "data_gaps_documented": True},
    "issues": [
        {"code": "MISSING_DOCUMENTATION", "path": "data/research/module_a_cache.jsonl", "detail": "2951 record(s) missing"},
        {"code": "PROVENANCE_INCOMPLETE", "path": "data/operational/state.json", "detail": "x"},
        {"code": "OUTPUT_HASH_MISMATCH", "path": "data/research/tim_v1_readiness.json", "detail": "output_hash"},
    ],
}
LIVENESS_PASS = {"datasets": [{"coverage": "100.000%", "status": "PASS", "source": "data/operational/rolling_liveness.json"}]}


def test_governance_only_fail_does_not_block_live_candles() -> None:
    data = _live_data()
    data["research_quality"] = dict(GOVERNANCE_ONLY_FAIL)
    data["operations"] = LIVENESS_PASS
    page = _setup_path_page(data)
    assert "Frische Daten, mindestens 20 Candles" in page
    assert "Research-Governance FAIL (Artefakte, nicht Kerzendaten)" in page


def test_governance_only_fail_still_blocks_when_liveness_fails() -> None:
    data = _live_data()
    data["research_quality"] = dict(GOVERNANCE_ONLY_FAIL)
    data["operations"] = {"datasets": [{"coverage": "90.000%", "status": "FAIL", "source": "data/operational/rolling_liveness.json"}]}
    assert "bestätigte Datenqualität fehlt" in _setup_path_page(data)


def test_report_fail_on_candle_checks_blocks() -> None:
    data = _live_data()
    data["research_quality"] = {"validation_status": "FAIL", "checks": {**GOVERNANCE_ONLY_FAIL["checks"], "timestamp_integrity": False}}
    data["operations"] = LIVENESS_PASS
    assert "bestätigte Datenqualität fehlt" in _setup_path_page(data)


def _blocked_with(**report: object) -> bool:
    data = _live_data()
    data["research_quality"] = {**GOVERNANCE_ONLY_FAIL, **report}
    data["operations"] = LIVENESS_PASS
    return "bestätigte Datenqualität fehlt" in _setup_path_page(data)


def test_report_fail_on_any_data_check_blocks() -> None:
    for check in ("schema_valid", "timestamp_integrity", "forward_only", "observe_only", "data_gaps_documented"):
        assert _blocked_with(checks={**GOVERNANCE_ONLY_FAIL["checks"], check: False}), check


def test_report_fail_with_data_issue_blocks_even_when_checks_pass() -> None:
    issues = GOVERNANCE_ONLY_FAIL["issues"] + [{"code": "MISSING_SOURCE", "path": "data/operational/events.jsonl", "detail": "File unavailable"}]
    assert _blocked_with(issues=issues)
    assert _blocked_with(issues=[])
    assert _blocked_with(checks={})


def test_governance_only_fail_without_liveness_stays_fail() -> None:
    data = _live_data()
    data["research_quality"] = dict(GOVERNANCE_ONLY_FAIL)
    page = _setup_path_page(data)
    assert "bestätigte Datenqualität fehlt" in page


def test_setup_path_survives_scenarios_none() -> None:
    chart = {"timeframe": "15m", "levels": {}, "analysis": {"market_state": "RANGE", "scenarios": None, "decision": {"status": "NO_TRADE"}}}
    from src.dashboard.pages.setup_path import _pipeline_stages
    assert _pipeline_stages(chart)["location"][0] == "MITTE"


def test_pipeline_stages_come_from_chart_analysis() -> None:
    chart = {
        "levels": {"range_low": 81000.0, "range_high": 82000.0},
        "analysis": {
            "market_state": "BALANCE", "auction_state": "ROTATION",
            "decision": {"status": "NO_TRADE"},
            "scenarios": [{"plan_text": "PLAN A LONG", "missing_confirmations": ["level_reclaimed"]}],
        },
    }
    page = _setup_path_page(_live_data(), chart)
    assert "Markt BALANCE · Auktion ROTATION" in page
    assert "AN KANTE" in page
    assert "fehlt: level_reclaimed" in page
    assert "kommen aus TIMs Pipeline" in page


def test_pipeline_stages_stay_required_without_analysis() -> None:
    page = _setup_path_page(_live_data())
    assert "REQUIRED" in page
    assert "brauchen TIMs Chart-Analyse" in page


def test_plan_against_market_state_is_marked_on_setup_path() -> None:
    from src.dashboard.pages.setup_path import _plan_lines

    scenario = {"id": "B", "direction": "LONG", "plan_text": "PLAN B LONG", "state": "WATCH", "missing_confirmations": ["reclaim"]}
    assert any("Gegen den Trend: Markt TREND_DOWN" in line for line in _plan_lines(scenario, "TREND_DOWN"))
    assert not any("Gegen den Trend" in line for line in _plan_lines(scenario, "TREND_UP"))
    assert not any("Gegen den Trend" in line for line in _plan_lines({**scenario, "direction": "SHORT"}, "TREND_DOWN"))
