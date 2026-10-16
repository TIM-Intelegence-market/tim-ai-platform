import json
import math

import pytest

from src.server_readiness.benchmark import compare_runs


MODEL = "qwen-test"
IN = "a" * 64
OUT = "b" * 64
CODE = "c" * 40


def run(case_id, duration, **changes):
    value = {
        "case_id": case_id,
        "input_sha256": IN,
        "output_sha256": OUT,
        "code_sha": CODE,
        "model": MODEL,
        "duration_seconds": duration,
    }
    value.update(changes)
    return value


def pairs():
    mac = [run("case-1", 10), run("case-2", 8.0)]
    server = [run("case-2", 2), run("case-1", 5.0)]
    return mac, server


def test_unordered_identical_pairs_pass_with_median_ratio():
    mac, server = pairs()
    result = compare_runs(mac, server, required_model=MODEL)
    assert result == {"status": "PASS", "reasons": [], "case_count": 2, "median_speed_ratio": 3.0}
    assert isinstance(result["median_speed_ratio"], float)
    assert json.loads(json.dumps(result)) == result


def test_single_pair_is_not_rounded():
    result = compare_runs([run("x", 1)], [run("x", 3)], required_model=MODEL)
    assert result["status"] == "PASS"
    assert result["case_count"] == 1
    assert result["median_speed_ratio"] == 1 / 3


@pytest.mark.parametrize(
    "field,value",
    [("input_sha256", "d" * 64), ("code_sha", "e" * 40), ("output_sha256", "f" * 64)],
)
def test_hash_mismatch_fails_naming_case_and_field(field, value):
    mac, server = pairs()
    server[1][field] = value
    result = compare_runs(mac, server, required_model=MODEL)
    assert result == {
        "status": "FAIL",
        "reasons": [f"case case-1: {field} mismatch"],
        "case_count": 0,
        "median_speed_ratio": None,
    }


def test_server_model_mismatch_fails():
    mac, server = pairs()
    server[0]["model"] = "other-model"
    result = compare_runs(mac, server, required_model=MODEL)
    assert result["status"] == "FAIL"
    assert result["reasons"] == ["case case-2: model does not match required_model"]
    assert result["median_speed_ratio"] is None


def test_mac_model_is_not_checked_against_required_model():
    mac, server = pairs()
    mac[0]["model"] = "mac-local-build"
    assert compare_runs(mac, server, required_model=MODEL)["status"] == "PASS"


def test_multiple_mismatches_are_sorted():
    mac, server = pairs()
    server[0]["output_sha256"] = "f" * 64
    server[1]["input_sha256"] = "f" * 64
    result = compare_runs(mac, server, required_model=MODEL)
    assert result["reasons"] == ["case case-1: input_sha256 mismatch", "case case-2: output_sha256 mismatch"]


@pytest.mark.parametrize("side", ["mac", "server"])
def test_duplicate_case_ids_are_blocked(side):
    mac, server = pairs()
    target = mac if side == "mac" else server
    target.append(run("case-1", 4))
    result = compare_runs(mac, server, required_model=MODEL)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == [f"{side}_runs contains duplicate case_id case-1"]
    assert result["case_count"] == 0 and result["median_speed_ratio"] is None


def test_missing_cases_are_blocked_not_inferred():
    mac, server = pairs()
    result = compare_runs(mac, server[:1], required_model=MODEL)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["case case-1 missing from server_runs"]
    result = compare_runs(mac + [run("case-3", 1)], server + [run("case-4", 1)], required_model=MODEL)
    assert result["reasons"] == ["case case-3 missing from server_runs", "case case-4 missing from mac_runs"]


@pytest.mark.parametrize("key", ["case_id", "input_sha256", "output_sha256", "code_sha", "model", "duration_seconds"])
def test_missing_field_is_blocked(key):
    mac, server = pairs()
    del server[0][key]
    result = compare_runs(mac, server, required_model=MODEL)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["server_runs contains an invalid row"]


def test_extra_field_is_blocked():
    mac, server = pairs()
    mac[0]["extra"] = 1
    assert compare_runs(mac, server, required_model=MODEL)["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "duration",
    [0, 0.0, -1, -0.5, True, False, math.nan, math.inf, -math.inf, 10**400, -(10**400), "1", None],
)
def test_invalid_durations_are_blocked(duration):
    mac, server = pairs()
    mac[0]["duration_seconds"] = duration
    result = compare_runs(mac, server, required_model=MODEL)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["mac_runs contains an invalid row"]


@pytest.mark.parametrize(
    "changes",
    [
        {"case_id": ""},
        {"case_id": 1},
        {"input_sha256": "A" * 64},
        {"output_sha256": "a" * 63},
        {"code_sha": "c" * 64},
        {"code_sha": "C" * 40},
        {"model": ""},
        {"model": None},
    ],
)
def test_malformed_rows_are_blocked(changes):
    mac, server = pairs()
    server[0].update(changes)
    assert compare_runs(mac, server, required_model=MODEL)["status"] == "BLOCKED"


@pytest.mark.parametrize("bad", [[], None, {}, "x", [None], ["row"], ({"case_id": "x"},)])
def test_invalid_inputs_are_blocked_without_raising(bad):
    mac, server = pairs()
    assert compare_runs(bad, server, required_model=MODEL)["status"] == "BLOCKED"
    assert compare_runs(mac, bad, required_model=MODEL)["status"] == "BLOCKED"


@pytest.mark.parametrize("model", ["", None, 1, ["qwen-test"]])
def test_invalid_required_model_is_blocked(model):
    mac, server = pairs()
    result = compare_runs(mac, server, required_model=model)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["required_model must be a non-empty string"]


def test_overflowing_ratio_is_blocked():
    result = compare_runs([run("x", 1e308)], [run("x", 1e-308)], required_model=MODEL)
    assert result["status"] == "BLOCKED"
    assert result["median_speed_ratio"] is None
