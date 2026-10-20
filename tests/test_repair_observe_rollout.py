import pytest

from src.repair_observe.rollout import (
    rollout_checklist,
    safe_stop_steps,
    validate_observe_config,
)


def valid_config(**overrides):
    cfg = {"AUTO_REPAIR": False, "MODE": "OBSERVE"}
    cfg.update(overrides)
    return cfg


def valid_status(**overrides):
    status = {
        "config": valid_config(),
        "metrics": {"events_ingested": 1000},
        "safe_stop_doc": "docs/safe-stop.md",
        "rollback_doc": "docs/rollback.md",
        "a1_decision": "GO",
    }
    status.update(overrides)
    return status


def test_valid_config():
    assert validate_observe_config(valid_config()) == {"ok": True, "violations": []}


@pytest.mark.parametrize("cfg", [None, [], "AUTO_REPAIR=false", 0])
def test_non_dict_config(cfg):
    assert validate_observe_config(cfg) == {
        "ok": False,
        "violations": ["config must be a dict"],
    }


def test_missing_keys_are_sorted_violations():
    assert validate_observe_config({}) == {
        "ok": False,
        "violations": ["AUTO_REPAIR missing", "MODE missing"],
    }


@pytest.mark.parametrize("value", [True, "true", "false", 0, None, 0.0, "False", [False]])
def test_auto_repair_must_be_bool_false(value):
    result = validate_observe_config(valid_config(AUTO_REPAIR=value))
    assert result == {"ok": False, "violations": ["AUTO_REPAIR must be False"]}


@pytest.mark.parametrize("value", ["observe", "ACT", "", None, ["OBSERVE"]])
def test_mode_must_be_observe(value):
    result = validate_observe_config(valid_config(MODE=value))
    assert result == {"ok": False, "violations": ["MODE must be OBSERVE"]}


@pytest.mark.parametrize("flag", ["TIM_LIVE_TRADING", "TIM_EXECUTION_ENABLED"])
@pytest.mark.parametrize("value", ["0", 0, False, "false"])
def test_trading_flags_disabled_values_pass(flag, value):
    assert validate_observe_config(valid_config(**{flag: value}))["ok"] is True


@pytest.mark.parametrize("flag", ["TIM_LIVE_TRADING", "TIM_EXECUTION_ENABLED"])
@pytest.mark.parametrize(
    "value", ["1", 1, True, "true", "FALSE", 0.0, None, "", [], {"a": 1}, {0}]
)
def test_trading_flags_enabled_or_invalid_values_fail(flag, value):
    result = validate_observe_config(valid_config(**{flag: value}))
    assert result == {"ok": False, "violations": [f"{flag} must be disabled"]}


def test_all_violations_reported_sorted():
    result = validate_observe_config(
        {"AUTO_REPAIR": "true", "MODE": "ACT", "TIM_LIVE_TRADING": 1,
         "TIM_EXECUTION_ENABLED": True}
    )
    assert result["ok"] is False
    assert result["violations"] == sorted([
        "AUTO_REPAIR must be False",
        "MODE must be OBSERVE",
        "TIM_LIVE_TRADING must be disabled",
        "TIM_EXECUTION_ENABLED must be disabled",
    ])


ITEMS = [
    "observe_config_valid",
    "metrics_available",
    "safe_stop_procedure_documented",
    "rollback_procedure_documented",
    "a1_decision_recorded",
]


def test_checklist_all_passed_in_fixed_order():
    assert rollout_checklist(valid_status()) == [
        {"item": item, "passed": True} for item in ITEMS
    ]


def test_checklist_no_go_counts_as_recorded():
    assert rollout_checklist(valid_status(a1_decision="NO_GO"))[4] == {
        "item": "a1_decision_recorded", "passed": True,
    }


@pytest.mark.parametrize("status", [None, [], "status", 1])
def test_checklist_non_dict_status_all_false(status):
    assert rollout_checklist(status) == [{"item": item, "passed": False} for item in ITEMS]


def test_checklist_empty_dict_all_false():
    assert [entry["passed"] for entry in rollout_checklist({})] == [False] * 5


@pytest.mark.parametrize(
    ("overrides", "index"),
    [
        ({"config": valid_config(AUTO_REPAIR=True)}, 0),
        ({"config": None}, 0),
        ({"metrics": {}}, 1),
        ({"metrics": [1]}, 1),
        ({"safe_stop_doc": ""}, 2),
        ({"safe_stop_doc": None}, 2),
        ({"rollback_doc": ""}, 3),
        ({"rollback_doc": 1}, 3),
        ({"a1_decision": "go"}, 4),
        ({"a1_decision": None}, 4),
        ({"a1_decision": ["GO"]}, 4),
    ],
)
def test_checklist_single_item_fails(overrides, index):
    result = rollout_checklist(valid_status(**overrides))
    assert [entry["item"] for entry in result] == ITEMS
    assert [entry["passed"] for entry in result] == [i != index for i in range(5)]


def test_safe_stop_steps_fixed():
    assert safe_stop_steps() == (
        "set AUTO_REPAIR=false",
        "stop the repair worker",
        "preserve incident evidence",
        "escalate to the operator",
    )
    assert isinstance(safe_stop_steps(), tuple)
