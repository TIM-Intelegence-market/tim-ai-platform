from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.insights import ResearchInsightsEngine


BASE = datetime(2026, 7, 1, tzinfo=timezone.utc)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def observation(index: int, *, rule: str = "1.0.0", test_only: bool = False) -> dict:
    return {
        "observation_id": f"obs-{index}",
        "kind": "RISING_CVD_ACTIVITY",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "observed_at": (BASE + timedelta(minutes=index)).isoformat(),
        "evidence": [{"metric": "net_delta", "value": "2"}, {"metric": "trades_per_second", "value": "4"}],
        "rule_version": rule,
        "input_hash": digest(f"input-{index}"),
        "provenance": "TEST_ONLY" if test_only else "BINANCE_SPOT_AGGTRADE_DETERMINISTIC",
        "mode": "OBSERVE",
    }


def validation(index: int, *, version: str = "1.0.0", complete: bool = True, test_only: bool = False) -> dict:
    horizons = [
        {"minutes": 5, "price_change_percent": "1", "net_delta": "2"},
        {"minutes": 15, "price_change_percent": "2", "net_delta": "4"},
        {"minutes": 30, "price_change_percent": "3", "net_delta": "6"},
    ] if complete else [{"minutes": 5, "price_change_percent": "1", "net_delta": "2"}]
    return {
        "observation_id": f"obs-{index}",
        "observed_at": (BASE + timedelta(minutes=index)).isoformat(),
        "validated_through": (BASE + timedelta(minutes=index + (30 if complete else 5))).isoformat(),
        "horizons": horizons,
        "complete": complete,
        "outcome": "PRICE_INCREASED" if complete else None,
        "validation_hash": digest(f"validation-{index}"),
        "validation_version": version,
        "mode": "TEST_ONLY" if test_only else "OBSERVE",
    }


def case(index: int, *, test_only: bool = False) -> dict:
    return {"case_id": f"case-{index}", "opened_at": BASE.isoformat(), "observation_ids": [f"obs-{index}"], "documentation": "TEST_ONLY" if test_only else "research"}


def manifest() -> dict:
    return {
        "core_version": "1.0.0", "status": "FROZEN", "operating_mode": "OBSERVE",
        "components": {"orderflow_metrics": "1.0.0", "orderflow_observations": "1.0.0", "orderflow_validation": "1.0.0"},
    }


def quality(**updates) -> dict:
    return {"coverage_percent": "100", "known_data_gaps": [], "integrity_errors": 0, "replay_status": "PASS", **updates}


def analyze(observations=None, validations=None, cases=None, **kwargs):
    return ResearchInsightsEngine().analyze(observations or [], validations or [], cases or [], manifest(), quality(**kwargs), generated_at="2026-07-31T23:59:59+00:00")


def test_identical_replay_produces_identical_statistics_and_exports():
    args = ([observation(1)], [validation(1)], [case(1)])
    first, second = analyze(*args), analyze(*reversed([list(reversed(x)) for x in args])) if False else analyze(*args)
    assert first == second
    assert ResearchInsightsEngine.to_json(first) == ResearchInsightsEngine.to_json(second)
    assert ResearchInsightsEngine.to_csv(first) == ResearchInsightsEngine.to_csv(second)
    assert ResearchInsightsEngine.to_markdown(first) == ResearchInsightsEngine.to_markdown(second)


def test_different_rule_and_validation_versions_are_separate():
    result = analyze([observation(1), observation(2, rule="1.1.0")], [validation(1), validation(2, version="1.1.0")], [case(1), case(2)])
    groups = {(item["versions"]["rule"], item["versions"]["validation"]) for item in result["outcome_distribution"]}
    assert groups == {("1.0.0", "1.0.0"), ("1.1.0", "1.1.0")}
    assert result["eligibility"]["version_consistent"] is False


def test_test_only_data_are_excluded():
    result = analyze([observation(1), observation(2, test_only=True), observation(3)], [validation(1), validation(2), validation(3)], [case(1), case(2), case(3, test_only=True)])
    assert result["sample_size"] == 1
    assert {item["reason"] for item in result["exclusions"]} == {"TEST_ONLY", "TEST_ONLY_CASE"}


def test_evidence_combinations_ignore_observed_values_and_source_hashes():
    first, second = observation(1), observation(2)
    first["evidence"] = [{"condition": "delta_positive", "value": "1", "source_hash": "a"*64}, {"condition": "activity_high", "value": "10"}]
    second["evidence"] = [{"condition": "activity_high", "value": "99"}, {"condition": "delta_positive", "value": "5", "source_hash": "b"*64}]
    result = analyze([first, second], [validation(1), validation(2)], [case(1), case(2)])
    assert result["evidence_combinations"] == [{"observation_type":"RISING_CVD_ACTIVITY","rule_version":"1.0.0","evidence":["activity_high","delta_positive"],"count":2,"outcomes":{"PRICE_DECREASED":0,"PRICE_INCREASED":2,"PRICE_SIDEWAYS":0},"sample_label":"N_LT_10"}]


def test_open_and_incomplete_are_not_counted_as_complete_outcomes():
    result = analyze([observation(1), observation(2), observation(3)], [validation(2, complete=False), validation(3)], [case(1), case(2), case(3)])
    item = result["outcome_distribution"][0]
    assert (item["fully_validated_cases"], item["open_cases"], item["incomplete_validations"]) == (1, 1, 1)


@pytest.mark.parametrize("n,label", [(1, "N_LT_10"), (10, "N_LT_30"), (30, "N_LT_100"), (100, "N_GTE_100"), (1000, "N_GTE_1000")])
def test_sample_labels(n, label):
    result = analyze([observation(i) for i in range(n)], [validation(i) for i in range(n)], [case(i) for i in range(n)])
    assert result["outcome_distribution"][0]["sample_label"] == label


def test_known_data_gaps_are_visible():
    result = analyze([observation(1)], [validation(1)], [case(1)], known_data_gaps=[{"start": "2026-07-01T00:00:00Z"}])
    assert result["data_quality"]["known_data_gaps"]
    assert "KNOWN_DATA_GAPS" in result["warnings"]


def test_capped_persisted_read_window_blocks_eligibility():
    result = ResearchInsightsEngine().analyze([observation(i) for i in range(1000)], [validation(i) for i in range(1000)], [case(i) for i in range(1000)], manifest(), {**quality(), "source_window_complete": False}, generated_at="2026-07-31T23:59:59+00:00")
    assert result["eligibility_status"] == "NOT_YET_ELIGIBLE"
    assert "PERSISTED_SOURCE_WINDOW_INCOMPLETE" in result["warnings"]


def test_median_percentiles_and_mean_are_exact():
    validations = [validation(i) for i in range(1, 5)]
    for index, item in enumerate(validations, 1):
        item["horizons"][0]["price_change_percent"] = str(index)
    result = analyze([observation(i) for i in range(1, 5)], validations, [case(i) for i in range(1, 5)])
    stats = result["followup_statistics"][0]["horizons"][0]["price_change_percent"]
    assert stats == {"n": 4, "minimum": "1", "maximum": "4", "mean": "2.5", "median": "2.5", "standard_deviation": "1.11803399", "percentile_25": "1.75", "percentile_75": "3.25", "interquartile_range": "1.5"}


def test_inputs_are_not_mutated():
    observations, validations, cases = [observation(1)], [validation(1)], [case(1)]
    before = copy.deepcopy((observations, validations, cases))
    analyze(observations, validations, cases)
    assert (observations, validations, cases) == before


@pytest.mark.parametrize("corruption", ["hash", "timestamp", "outcome", "evidence"])
def test_corrupt_inputs_are_rejected(corruption):
    obs, val = observation(1), validation(1)
    if corruption == "hash": obs["input_hash"] = "bad"
    if corruption == "timestamp": obs["observed_at"] = "not-a-time"
    if corruption == "outcome": val["outcome"] = "PREDICTION"
    if corruption == "evidence": obs["evidence"] = []
    with pytest.raises(ValueError):
        analyze([obs], [val], [case(1)])


def test_missing_data_do_not_create_values():
    result = analyze([observation(1)], [], [case(1)])
    assert result["outcome_distribution"][0]["fully_validated_cases"] == 0
    assert all(item["price_change_percent"] is None for item in result["followup_statistics"][0]["horizons"])
    assert result["result_status"] == "INSUFFICIENT_SAMPLE"


def test_output_hash_covers_output_and_dashboard_contract_is_read_only():
    result = analyze([observation(1)], [validation(1)], [case(1)])
    without_hash = dict(result); output_hash = without_hash.pop("output_hash")
    assert output_hash == hashlib.sha256(json.dumps(without_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()
    assert result["read_only"] is True and result["mode"] == "OBSERVE"
    assert "NOT_YET_ELIGIBLE" in result["warnings"]
