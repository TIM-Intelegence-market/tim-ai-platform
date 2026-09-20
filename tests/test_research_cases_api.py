from src.dashboard.app import _research_cases_collection


def snapshot():
    return {"research_cases": [
        {"case_id": "case_a", "status": "OPEN", "timeframe": "1m", "symbol": "BTCUSDT",
         "observation_ids": ["o1"], "evidence": [{"kind": "BOS_BULLISH"}], "missing_evidence": ["x"],
         "outcome": None, "rule_versions": {"bos": "1.0.0"}},
        {"case_id": "case_b", "status": "CONFIRMED", "timeframe": "5m", "symbol": "BTCUSDT",
         "observation_ids": ["o2", "o3"], "evidence": [{"kind": "REJECTION"}], "missing_evidence": [],
         "outcome": "documented", "rule_versions": {"bronxc": "1.0.0"}},
    ]}


def test_collection_no_implicit_confirmed_restriction() -> None:
    payload = _research_cases_collection(snapshot(), {})
    assert payload["stats"]["total"] == 2
    assert [c["case_id"] for c in payload["cases"]] == ["case_a", "case_b"]


def test_collection_status_filter() -> None:
    payload = _research_cases_collection(snapshot(), {"status": ["CONFIRMED"]})
    assert [c["case_id"] for c in payload["cases"]] == ["case_b"]
    assert payload["stats"]["total"] == 2


def test_collection_stats_real() -> None:
    payload = _research_cases_collection(snapshot(), {}, stats_only=True)
    assert payload["stats"]["by_status"] == {"CONFIRMED": 1, "OPEN": 1}
    assert payload["stats"]["confirmed"] == 1
    assert payload["stats"]["pending_outcome"] == 1
    assert payload["stats"]["missing_evidence"] == {"x": 1}


def test_collection_pagination_cursor() -> None:
    first = _research_cases_collection(snapshot(), {"limit": ["1"]})
    assert first["pagination"] == {"limit": 1, "returned": 1, "total_matching": 2, "next_cursor": "case_a"}
    second = _research_cases_collection(snapshot(), {"limit": ["1"], "cursor": ["case_a"]})
    assert [c["case_id"] for c in second["cases"]] == ["case_b"]
    assert second["pagination"]["next_cursor"] is None


def test_collection_detail_lookup_logic() -> None:
    snap = snapshot()
    found = next((c for c in snap["research_cases"] if c["case_id"] == "case_b"), None)
    assert found is not None and found["outcome"] == "documented"
