import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from src.server_readiness.bootstrap import REQUIRED_GATES, evaluate_bootstrap


NOW = datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
EVIDENCE = "sha256:" + "a" * 64


def record(gate, status="PASS", observed_at=None, evidence_ref=EVIDENCE):
    return {
        "gate": gate,
        "status": status,
        "observed_at": (observed_at or NOW - timedelta(minutes=5)).isoformat(),
        "evidence_ref": evidence_ref,
    }


def bundle():
    return [record(gate) for gate in REQUIRED_GATES]


def test_required_gates_are_exact():
    assert REQUIRED_GATES == (
        "debian_13",
        "encrypted_reboot",
        "key_only_ssh",
        "direct_github",
        "worker_smoke",
        "portal_systemd",
        "network_acceptance",
        "operations_acceptance",
        "git_reconciliation",
    )


def test_complete_fresh_bundle_passes():
    result = evaluate_bootstrap(list(reversed(bundle())), now=NOW)
    assert result == {"status": "PASS", "reasons": [], "missing": [], "executed": False}
    assert json.loads(json.dumps(result)) == result


def test_accepts_z_suffix():
    records = bundle()
    records[0]["observed_at"] = "2026-01-02T11:00:00Z"
    assert evaluate_bootstrap(records, now=NOW)["status"] == "PASS"


@pytest.mark.parametrize("gate", REQUIRED_GATES)
def test_each_missing_gate_is_blocked(gate):
    records = [item for item in bundle() if item["gate"] != gate]
    result = evaluate_bootstrap(records, now=NOW)
    assert result == {
        "status": "BLOCKED",
        "reasons": [f"{gate}: missing record"],
        "missing": [gate],
        "executed": False,
    }


def test_explicit_fail_takes_precedence_over_missing_gate():
    records = [item for item in bundle() if item["gate"] != "worker_smoke"]
    records[0]["status"] = "FAIL"
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "FAIL"
    assert result["missing"] == ["worker_smoke"]
    assert result["reasons"] == ["debian_13: status FAIL", "worker_smoke: missing record"]
    assert result["executed"] is False


def test_explicit_fail_takes_precedence_over_stale_record():
    records = bundle()
    records[0]["status"] = "FAIL"
    records[1]["observed_at"] = (NOW - timedelta(days=3)).isoformat()
    assert evaluate_bootstrap(records, now=NOW)["status"] == "FAIL"


def test_explicit_blocked_status_is_blocked():
    records = bundle()
    records[2]["status"] = "BLOCKED"
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["key_only_ssh: status BLOCKED"]
    assert result["missing"] == []


def test_duplicate_gate_is_blocked():
    records = bundle() + [record("direct_github")]
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["direct_github: duplicate record"]


def test_unknown_gate_is_blocked_without_echo():
    records = bundle() + [record("rm -rf /")]
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["unknown gate"]


@pytest.mark.parametrize(
    "evidence",
    ["a" * 64, "sha256:" + "A" * 64, "sha256:" + "a" * 63, "sha256:" + "a" * 64 + "\n", "md5:" + "a" * 64, None, 1],
)
def test_invalid_evidence_hash_is_blocked(evidence):
    records = bundle()
    records[3]["evidence_ref"] = evidence
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["direct_github: invalid evidence_ref"]


def test_naive_timestamp_is_blocked():
    records = bundle()
    records[4]["observed_at"] = "2026-01-02T11:00:00"
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["worker_smoke: invalid observed_at"]


@pytest.mark.parametrize("value", ["not a date", "", None, 12345])
def test_invalid_timestamp_is_blocked(value):
    records = bundle()
    records[4]["observed_at"] = value
    assert evaluate_bootstrap(records, now=NOW)["reasons"] == ["worker_smoke: invalid observed_at"]


def test_future_timestamp_is_blocked():
    records = bundle()
    records[5]["observed_at"] = (NOW + timedelta(seconds=1)).isoformat()
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["portal_systemd: observed_at is in the future"]


def test_age_boundary_equal_is_fresh_and_greater_is_stale():
    # Choice: age == max_age_seconds is fresh; age > max_age_seconds is stale.
    records = bundle()
    records[6]["observed_at"] = (NOW - timedelta(seconds=86400)).isoformat()
    assert evaluate_bootstrap(records, now=NOW, max_age_seconds=86400)["status"] == "PASS"
    records[6]["observed_at"] = (NOW - timedelta(seconds=86400, microseconds=1)).isoformat()
    result = evaluate_bootstrap(records, now=NOW, max_age_seconds=86400)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["network_acceptance: observed_at is stale"]


@pytest.mark.parametrize("now", [datetime(2026, 1, 2, 12), "2026-01-02T12:00:00+00:00", None, 0])
def test_invalid_or_naive_now_is_blocked(now):
    result = evaluate_bootstrap(bundle(), now=now)
    assert result["status"] == "BLOCKED"
    assert "now must be a timezone-aware datetime" in result["reasons"]


@pytest.mark.parametrize("max_age", [True, False, -1, -0.1, math.nan, math.inf, 10**400, "86400", None])
def test_invalid_max_age_is_blocked(max_age):
    result = evaluate_bootstrap(bundle(), now=NOW, max_age_seconds=max_age)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["max_age_seconds must be a finite non-negative number"]


@pytest.mark.parametrize("records", [None, {}, "x", (), 5])
def test_non_list_records_are_blocked(records):
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["missing"] == sorted(REQUIRED_GATES)
    assert result["executed"] is False


def test_empty_records_are_blocked_with_all_gates_missing():
    result = evaluate_bootstrap([], now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["missing"] == sorted(REQUIRED_GATES)


@pytest.mark.parametrize(
    "bad",
    [None, "row", [], {"gate": "debian_13"}, {**record("debian_13"), "extra": 1}, {"gate": ["x"], "status": 1, "observed_at": 1, "evidence_ref": 1}],
)
def test_malformed_records_are_blocked_without_raising(bad):
    result = evaluate_bootstrap(bundle() + [bad], now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["executed"] is False


def test_invalid_status_is_blocked():
    records = bundle()
    records[7]["status"] = "pass"
    result = evaluate_bootstrap(records, now=NOW)
    assert result["status"] == "BLOCKED"
    assert result["reasons"] == ["operations_acceptance: invalid status"]
