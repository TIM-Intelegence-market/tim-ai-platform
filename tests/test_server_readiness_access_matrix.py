from datetime import datetime, timedelta, timezone

import pytest

from src.server_readiness.access_matrix import REQUIRED_CASES, evaluate_access_matrix


NOW = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
EVIDENCE = "sha256:" + "a" * 64


def observation(role, target, reachable, observed_at=NOW, evidence_ref=EVIDENCE):
    return {
        "role": role,
        "target": target,
        "reachable": reachable,
        "observed_at": observed_at.isoformat(),
        "evidence_ref": evidence_ref,
    }


def complete_matrix():
    return [
        observation(role, target, allowed)
        for (role, target), allowed in REQUIRED_CASES.items()
    ]


def test_passes_complete_matrix():
    assert evaluate_access_matrix(complete_matrix(), now=NOW) == {
        "status": "PASS",
        "violations": [],
        "missing": [],
        "changes_applied": False,
    }


@pytest.mark.parametrize("missing_case", sorted(REQUIRED_CASES))
def test_blocks_each_missing_case(missing_case):
    observations = [item for item in complete_matrix() if (item["role"], item["target"]) != missing_case]
    result = evaluate_access_matrix(observations, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["missing"] == [f"{missing_case[0]}/{missing_case[1]}"]


@pytest.mark.parametrize(
    "role,target",
    [("outsider", "idrac"), ("outsider", "server_ssh"), ("member", "idrac")],
)
def test_forbidden_reachability_triggers_safe_stop(role, target):
    observations = complete_matrix()
    for item in observations:
        if item["role"] == role and item["target"] == target:
            item["reachable"] = True
    assert evaluate_access_matrix(observations, now=NOW)["status"] == "SAFE_STOP"


def test_missing_matrix_plus_forbidden_reachability_is_safe_stop():
    result = evaluate_access_matrix(
        [observation("outsider", "idrac", True)], now=NOW
    )
    assert result["status"] == "SAFE_STOP"
    assert "admin/idrac" in result["missing"]


@pytest.mark.parametrize(
    "items",
    [
        lambda: complete_matrix() + [observation("admin", "idrac", True)],
        lambda: complete_matrix() + [observation("unknown", "idrac", False)],
    ],
)
def test_rejects_duplicate_or_unknown_cases(items):
    result = evaluate_access_matrix(items(), now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["violations"]


@pytest.mark.parametrize("value", [1, 0, "true", None])
def test_rejects_non_boolean_reachability(value):
    observations = complete_matrix()
    observations[0]["reachable"] = value
    result = evaluate_access_matrix(observations, now=NOW)
    assert result["status"] == "BLOCKED"
    assert "admin/idrac" in result["missing"]


@pytest.mark.parametrize(
    "evidence_ref",
    ["sha256:" + "a" * 63, "sha256:" + "A" * 64, "not-a-hash"],
)
def test_rejects_invalid_evidence_hash(evidence_ref):
    observations = complete_matrix()
    observations[0]["evidence_ref"] = evidence_ref
    result = evaluate_access_matrix(observations, now=NOW)
    assert result["status"] == "BLOCKED"
    assert "admin/idrac" in result["missing"]


@pytest.mark.parametrize(
    "observed_at",
    [NOW.replace(tzinfo=None), NOW + timedelta(seconds=1), NOW - timedelta(seconds=3601)],
)
def test_rejects_naive_future_or_stale_timestamp(observed_at):
    observations = complete_matrix()
    observations[0]["observed_at"] = observed_at.isoformat()
    result = evaluate_access_matrix(observations, now=NOW)
    assert result["status"] == "BLOCKED"
    assert "admin/idrac" in result["missing"]


def test_rejects_invalid_now_and_age_without_raising():
    assert evaluate_access_matrix([], now=NOW.replace(tzinfo=None))["status"] == "BLOCKED"
    assert evaluate_access_matrix([], now=NOW, max_age_seconds=-1)["status"] == "BLOCKED"
    assert evaluate_access_matrix([], now=NOW, max_age_seconds=True)["status"] == "BLOCKED"


def test_bad_input_does_not_echo_arbitrary_strings():
    result = evaluate_access_matrix(
        [{"role": "secret-value", "target": "secret-target"}], now=NOW
    )
    assert result["status"] == "BLOCKED"
    assert "secret-value" not in str(result)
    assert "secret-target" not in str(result)
