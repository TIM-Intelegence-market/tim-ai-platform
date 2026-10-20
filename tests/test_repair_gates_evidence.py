import hashlib
import json

from src.bugfixer.safety import Policy
from src.repair_gates import aggregate, autonomy, forbidden
from src.repair_gates.evidence_gates import REPORT_GATES, gates_from_refs
from src.repair_gates.result import GateResult, GateStatus
from src.repair_gates.secret_scan import scan


def write_report(tmp_path, name, status):
    path = tmp_path / f"{name}.json"
    data = json.dumps({"status": status}).encode()
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def complete_refs(tmp_path):
    return {
        name: write_report(tmp_path, name, "FAIL_AS_EXPECTED" if name == "pre_repair_repro" else "PASS")
        for name in REPORT_GATES
    }


def test_all_valid_reports_pass(tmp_path):
    results = gates_from_refs(complete_refs(tmp_path))
    assert [result.status for result in results] == [GateStatus.PASS] * len(REPORT_GATES)
    assert [result.gate for result in results] == list(REPORT_GATES)


def test_missing_reference_fails(tmp_path):
    refs = complete_refs(tmp_path)
    del refs["runtime"]
    result = gates_from_refs(refs)[2]
    assert result.status is GateStatus.FAIL
    assert result.reason == "missing evidence reference"


def test_unreadable_report_fails(tmp_path):
    refs = complete_refs(tmp_path)
    refs["runtime"]["path"] = str(tmp_path / "missing.json")
    result = gates_from_refs(refs)[2]
    assert result.status is GateStatus.FAIL
    assert tuple(result.evidence_refs) == (refs["runtime"]["path"],)


def test_invalid_json_fails(tmp_path):
    refs = complete_refs(tmp_path)
    path = tmp_path / "bad.json"
    path.write_bytes(b"not json")
    refs["runtime"] = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert gates_from_refs(refs)[2].status is GateStatus.FAIL


def test_hash_mismatch_fails(tmp_path):
    refs = complete_refs(tmp_path)
    refs["runtime"]["sha256"] = "0" * 64
    assert gates_from_refs(refs)[2].reason == "sha256 mismatch"


def test_pre_repair_requires_expected_failure(tmp_path):
    refs = complete_refs(tmp_path)
    refs["pre_repair_repro"] = write_report(tmp_path, "pre_repair_repro", "NOT_REPRODUCED")
    result = gates_from_refs(refs)[6]
    assert result.status is GateStatus.FAIL
    assert result.reason == "unexpected status: 'NOT_REPRODUCED'"


def test_missing_status_fails(tmp_path):
    refs = complete_refs(tmp_path)
    path = tmp_path / "missing-status.json"
    data = b"{}"
    path.write_bytes(data)
    refs["runtime"] = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    assert gates_from_refs(refs)[2].reason == "missing status"


def _row():
    return {
        "remediation_id": "repair-217",
        "version": 1,
        "autonomy_level": "A1",
        "risk": "LOW",
        "confidence": 0.95,
        "actions": ["observe"],
        "preconditions": ["ready"],
    }


def _all_results(tmp_path, monkeypatch, secret_text="clean text"):
    monkeypatch.setattr(autonomy, "_gate", lambda row, category, satisfied: ("PROPOSED", "eligible"))
    results = [autonomy.evaluate(_row(), "INVARIANT_VIOLATION", {"ready": True})]
    results.extend(gates_from_refs(complete_refs(tmp_path)))
    results.append(scan(secret_text))
    results.append(forbidden.check_action("observe"))
    results.append(forbidden.check_policy(Policy()))
    return results


def test_all_gate_results_aggregate_to_pass(tmp_path, monkeypatch):
    results = _all_results(tmp_path, monkeypatch)
    assert all(isinstance(result, GateResult) for result in results)
    out = aggregate.decide({result.gate for result in results}, results)
    assert out["status"] == "PASS"


def test_secret_in_scan_makes_aggregate_fail(tmp_path, monkeypatch):
    results = _all_results(tmp_path, monkeypatch, secret_text="password=hunter2")
    assert all(isinstance(result, GateResult) for result in results)
    out = aggregate.decide({result.gate for result in results}, results)
    assert out["status"] == "FAIL"
