from src.repair_gates import autonomy


def recipe(level="A1", risk="LOW", confidence=0.95, actions=None, preconditions=None):
    return {
        "remediation_id": "repair-217",
        "version": 1,
        "autonomy_level": level,
        "risk": risk,
        "confidence": confidence,
        "actions": actions if actions is not None else ["observe"],
        "preconditions": preconditions if preconditions is not None else ["ready"],
    }


def test_a4_is_fail(monkeypatch):
    monkeypatch.setattr(autonomy, "_gate", lambda row, category, satisfied: ("SAFE_STOP", "not autonomous"))
    result = autonomy.evaluate(recipe("A4"), "INVARIANT_VIOLATION", {"ready": True})
    assert result.name == "autonomy"
    assert result.status == "FAIL"
    assert result.reason == "SAFE_STOP: not autonomous"


def test_unknown_category_is_fail(monkeypatch):
    monkeypatch.setattr(autonomy, "_gate", lambda row, category, satisfied: ("UNKNOWN", "unknown category"))
    result = autonomy.evaluate(recipe(), "UNKNOWN", {"ready": True})
    assert result.status == "FAIL"


def test_a0_is_blocked(monkeypatch):
    monkeypatch.setattr(autonomy, "_gate", lambda row, category, satisfied: ("BLOCKED", "level not allowed"))
    result = autonomy.evaluate(recipe("A0"), "INVARIANT_VIOLATION", {"ready": True})
    assert result.status == "BLOCKED"


def test_a1_low_risk_observe_with_satisfied_preconditions_passes(monkeypatch):
    monkeypatch.setattr(autonomy, "_gate", lambda row, category, satisfied: ("PROPOSED", "eligible"))
    result = autonomy.evaluate(recipe(), "INVARIANT_VIOLATION", {"ready": True})
    assert result.status == "PASS"


def test_low_confidence_is_blocked(monkeypatch):
    monkeypatch.setattr(autonomy, "_gate", lambda row, category, satisfied: ("BLOCKED", "confidence too low"))
    result = autonomy.evaluate(recipe(confidence=0.5), "INVARIANT_VIOLATION", {"ready": True})
    assert result.status == "BLOCKED"


def test_missing_precondition_is_blocked(monkeypatch):
    monkeypatch.setattr(autonomy, "_gate", lambda row, category, satisfied: ("BLOCKED", "precondition missing"))
    result = autonomy.evaluate(recipe(), "INVARIANT_VIOLATION", {})
    assert result.status == "BLOCKED"
