from src.repair_observe import a2


def allow_a1(monkeypatch):
    monkeypatch.setattr(a2, "a1_go_no_go", lambda metrics: {"decision": "GO", "reasons": []})


def recipe(**overrides):
    value = {
        "remediation_id": "r1",
        "autonomy_level": "A2",
        "verified_runs": 20,
        "failed_runs": 0,
        "rollbacks": 0,
    }
    value.update(overrides)
    return value


def test_a2_go(monkeypatch):
    allow_a1(monkeypatch)
    result = a2.a2_go_no_go({}, [recipe()])
    assert result == {
        "decision": "GO",
        "recipes": {"r1": {"decision": "GO", "reasons": []}},
        "reasons": [],
        "auto_repair_enabled": False,
    }


def test_a1_no_go(monkeypatch):
    monkeypatch.setattr(a2, "a1_go_no_go", lambda metrics: {"decision": "NO_GO", "reasons": ["bad A1"]})
    result = a2.a2_go_no_go({}, [recipe()])
    assert result["decision"] == "NO_GO"
    assert result["reasons"] == ["A1 prerequisites not met", "bad A1"]


def test_each_recipe_criterion_can_fail(monkeypatch):
    allow_a1(monkeypatch)
    result = a2.a2_go_no_go({}, [
        recipe(remediation_id="autonomy", autonomy_level="A1"),
        recipe(remediation_id="verified", verified_runs=19),
        recipe(remediation_id="failed", failed_runs=1),
        recipe(remediation_id="rollback", rollbacks=1),
    ])
    assert all(item["decision"] == "NO_GO" for item in result["recipes"].values())


def test_a1_level_recipe_is_not_go(monkeypatch):
    allow_a1(monkeypatch)
    result = a2.a2_go_no_go({}, [recipe(autonomy_level="A1")])
    assert result["recipes"]["r1"]["decision"] == "NO_GO"


def test_duplicate_ids_are_no_go(monkeypatch):
    allow_a1(monkeypatch)
    result = a2.a2_go_no_go({}, [recipe(), recipe()])
    assert result["decision"] == "NO_GO"
    assert "Duplicate remediation_id" in result["reasons"]


def test_malformed_input_never_raises(monkeypatch):
    allow_a1(monkeypatch)
    result = a2.a2_go_no_go({}, [None, recipe(rollbacks=True)])
    assert result["decision"] == "NO_GO"
    assert result["auto_repair_enabled"] is False


def test_threshold_overrides(monkeypatch):
    allow_a1(monkeypatch)
    result = a2.a2_go_no_go({}, [recipe(verified_runs=10)], {"min_verified_runs": 10})
    assert result["decision"] == "GO"


def test_unknown_threshold_is_no_go(monkeypatch):
    allow_a1(monkeypatch)
    result = a2.a2_go_no_go({}, [recipe()], {"unexpected": 1})
    assert result["decision"] == "NO_GO"


def test_auto_repair_is_always_false(monkeypatch):
    allow_a1(monkeypatch)
    assert a2.a2_go_no_go({}, [recipe()])["auto_repair_enabled"] is False
