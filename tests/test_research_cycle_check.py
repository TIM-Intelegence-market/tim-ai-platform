from __future__ import annotations

import json
from pathlib import Path

from src.operational.research_cycle_check import ResearchCycleChecker


def test_cycle_checker_maps_health_and_persists_without_metrics_row(tmp_path, monkeypatch):
    checker = ResearchCycleChecker(tmp_path, "http://127.0.0.1:1", validator_cycle=47)
    health = {
        "status": "HEALTHY",
        "level": "GREEN",
        "checked_at": "2026-07-20T16:00:00+00:00",
        "warnings": [],
        "critical": [],
        "checks": {"router_logic": True, "no_trade_events": True},
    }
    monkeypatch.setattr(checker.health_checker, "check", lambda: health)

    summary = checker.run_full_check()

    assert summary["overall_status"] == "HEALTHY"
    assert summary["validator_cycle"] == 47
    assert summary["checks_pass"] == 2
    assert json.loads(checker.latest_path.read_text())["health"] == health
    assert not (tmp_path / "data/operational/metrics.jsonl").exists()
    event = json.loads((tmp_path / "data/operational/events.jsonl").read_text())
    assert event["event"] == "RESEARCH_CYCLE_CHECK"


def test_cycle_checker_reads_actual_cycles_key(tmp_path, monkeypatch):
    state = tmp_path / "data/operational/state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"cycles": 93}))
    checker = ResearchCycleChecker(tmp_path, "http://127.0.0.1:1")
    monkeypatch.setattr(
        checker.health_checker,
        "check",
        lambda: {
            "status": "DEGRADED",
            "level": "YELLOW",
            "checked_at": "2026-07-20T16:00:00+00:00",
            "warnings": ["llama32_ready"],
            "critical": [],
            "checks": {"llama32_ready": False},
        },
    )

    summary = checker.run_full_check(persist=False)

    assert summary["validator_cycle"] == 93
    assert summary["overall_status"] == "DEGRADED"
    assert summary["checks_warn"] == 1
    assert not checker.latest_path.exists()
